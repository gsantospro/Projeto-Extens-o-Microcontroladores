import threading, queue
from datetime import datetime
from nicegui import ui, app
import config
import serial_thread as serial_logic
import export_excel
import data

# ===================== Carrega dados na inicialização =====================
config.funcionarios = data.carregar_json(config.ARQ_FUNC, {})
config.registros = data.carregar_json(config.ARQ_REG, {})

# ===================== UI (NiceGUI) =====================
with ui.header().classes(replace='row items-center justify-between'):
    ui.button(icon='menu').props('flat color=white')
    with ui.tabs() as tabs:
        ui.tab('Conexão')
        ui.tab('Cadastro')
        ui.tab('Remover')
        ui.tab('Registros por Funcionário')
        ui.tab('Registros Totais (Dia)')
        ui.tab('Exportar Excel')
    status_label = ui.label('Desconectado').classes('text-red-600')

with ui.footer(value=False) as footer:
    ui.label('Trabalho Microcontroladores • Ponto NFC')

# ---------- Painéis por aba ----------
with ui.tab_panels(tabs, value='Conexão').classes('w-full'):
    # ====== ABA CONEXÃO ======
    with ui.tab_panel('Conexão'):
        with ui.row().classes('w-full items-end gap-4'):
            portas_select = ui.select(options=serial_logic.listar_portas(), label='Porta Serial', with_input=True)\
                              .classes('min-w-[220px]')
            portas_select.value = portas_select.options[0] if portas_select.options else None

            def refresh_ports():
                portas_select.options = serial_logic.listar_portas()
                ui.notify('Portas atualizadas', type='positive')

            def conectar():
                global serial_thread_obj
                
                if config.serial_connected:
                    ui.notify('Já conectado', type='warning'); return
                if not portas_select.value:
                    ui.notify('Selecione uma porta', type='warning'); return

                config.PORTA_ATUAL = portas_select.value
                ui.notify(f'Conectando em {config.PORTA_ATUAL}...', type='info')

                config.serial_stop_flag.clear()
                
                serial_thread_obj = threading.Thread(
                    target=serial_logic.serial_worker,
                    args=(config.PORTA_ATUAL, True), 
                    daemon=True
                )
                serial_thread_obj.start()

            def desconectar():
                if not config.serial_connected:
                    ui.notify('Já desconectado', type='warning'); return
                config.serial_stop_flag.set()
                ui.notify('Desconectando...', type='info')

            ui.button('Conectar', on_click=conectar, color='green')
            ui.button('Desconectar', on_click=desconectar, color='red')

    # ====== ABA CADASTRO ======
    with ui.tab_panel('Cadastro'):
        ui.label('Cadastrar funcionário').classes('text-lg font-medium')
        with ui.row().classes('items-end gap-3'):
            nome_in = ui.input('Nome').classes('min-w-[260px]')
            uid_in  = ui.input('UID (hex)').classes('min-w-[260px]')

            def capturar_uid():
                if not config.serial_connected:
                    ui.notify('Conecte à serial para capturar UID', type='warning'); return
                with config.capture_lock:
                    config.capture_uid_mode = True
                ui.notify('Aproxime o cartão para capturar UID...', type='info')

            ui.button('Capturar próximo UID', on_click=capturar_uid, icon='fingerprint')

        def salvar_funcionario():
            nome = (nome_in.value or '').strip()
            uid  = (uid_in.value or '').strip().upper()
            if not nome or not uid:
                ui.notify('Preencha nome e UID', type='warning'); return
            if not config.HEX_RE.match(uid):
                ui.notify('UID inválido (use somente HEX)', type='warning'); return
            if uid in config.funcionarios:
                ui.notify('UID já cadastrado', type='warning'); return
            config.funcionarios[uid] = nome
            data.salvar_json(config.ARQ_FUNC, config.funcionarios)
            ui.notify(f'Cadastrado: {nome} ({uid})', type='positive')
            atualizar_remover_ui()
            atualizar_tabela_batidas_por_func()
            nome_in.value = ''
            uid_in.value = ''

        ui.button('Salvar', on_click=salvar_funcionario, color='green')

    # ====== ABA REMOVER ======
    with ui.tab_panel('Remover'):
        ui.label('Remover funcionário').classes('text-lg font-medium')

        def _options_por_nome():
            contagem = {}
            for uid, nome in config.funcionarios.items():
                contagem[nome] = contagem.get(nome, 0) + 1
            opts = {}
            for uid, nome in sorted(config.funcionarios.items(), key=lambda x: x[1].lower()):
                label = nome if contagem[nome] == 1 else f'{nome} ({uid[:6]}...)'
                opts[uid] = label
            return opts

        sel_nome = ui.select(options=_options_por_nome(), label='Selecione pelo nome').classes('min-w-[420px]')
        apagar_chk = ui.checkbox('Apagar também os registros', value=False)

        def atualizar_remover_ui():
            sel_nome.options = _options_por_nome()
            sel_nome.value = None
            sel_nome.update()

        def remover_agora():
            uid = sel_nome.value
            if not uid:
                ui.notify('Selecione um funcionário', type='warning'); return
            nome = config.funcionarios.get(uid)
            if not nome:
                ui.notify('Funcionário não encontrado', type='warning'); return
            config.funcionarios.pop(uid, None)
            data.salvar_json(config.ARQ_FUNC, config.funcionarios)
            if apagar_chk.value:
                config.registros.pop(uid, None)
                data.salvar_json(config.ARQ_REG, config.registros)
            ui.notify(f'Funcionário "{nome}" removido do sistema.', type='positive')
            atualizar_remover_ui()
            try: atualizar_tabela_batidas_por_func()
            except: pass
            try: atualizar_lobby_table()
            except: pass

        ui.button('Remover funcionário', color='red', on_click=remover_agora)

# ====== ABA REGISTROS ======
    with ui.tab_panel('Registros por Funcionário'):
        ui.label('Registros por funcionário').classes('text-lg font-medium')

        def coletar_datas_disponiveis():
            """Retorna (options_dict, default_iso): options = {ISO: 'DD/MM/AAAA'}, ordenadas por mais recente."""
            datas = set()
            for _uid, dias in config.registros.items():
                datas.update(dias.keys())
            if not datas:
                hoje_iso = datetime.now().strftime("%Y-%m-%d")
                return {hoje_iso: datetime.strptime(hoje_iso, "%Y-%m-%d").strftime("%d/%m/%Y")}, hoje_iso

            ordenadas = sorted(datas, reverse=True)
            options = {iso: datetime.strptime(iso, "%Y-%m-%d").strftime("%d/%m/%Y") for iso in ordenadas}
            return options, ordenadas[0]

        datas_options, default_iso = coletar_datas_disponiveis()

        datas_select = ui.select(
            options=datas_options,
            value=default_iso,
            label='Data'
        ).classes('min-w-[210px]')

        batidas_container = ui.column().classes('w-full')

        def desenhar_batidas_por_func():
            batidas_container.clear()
            data_iso = datas_select.value or datetime.now().strftime("%Y-%m-%d")
            data_br = datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")

            for uid, nome in sorted(config.funcionarios.items(), key=lambda x: x[1].lower()):
                dia = config.registros.get(uid, {}).get(data_iso, {})
                with batidas_container:
                    with ui.expansion(f'{nome} ({uid}) - {data_br}', value=False).classes('w-full'):
                        with ui.card().classes('w-full'):
                            rows = [{
                                'entrada': dia.get('entrada', ''),
                                'saida_intervalo': dia.get('saida_intervalo', ''),
                                'volta_intervalo': dia.get('volta_intervalo', ''),
                                'saida': dia.get('saida', ''),
                            }]
                            ui.table(
                                columns=[
                                    {'name': 'entrada', 'label': 'Entrada', 'field': 'entrada'},
                                    {'name': 'saida_intervalo', 'label': 'Saída Intervalo', 'field': 'saida_intervalo'},
                                    {'name': 'volta_intervalo', 'label': 'Volta Intervalo', 'field': 'volta_intervalo'},
                                    {'name': 'saida', 'label': 'Saída', 'field': 'saida'},
                                ],
                                rows=rows,
                            ).classes('w-full')

        def atualizar_datas_select():
            """Recarrega as datas disponíveis e mantém a seleção quando possível."""
            old_val = datas_select.value
            options, default_iso_local = coletar_datas_disponiveis()
            datas_select.options = options
            datas_select.value = old_val if old_val in options else default_iso_local
            datas_select.update()

        def atualizar_tabela_batidas_por_func():
            desenhar_batidas_por_func()

        datas_select.on_value_change(lambda _: desenhar_batidas_por_func())

        desenhar_batidas_por_func()

    # ====== ABA REGISTROS TOTAIS ======
    with ui.tab_panel('Registros Totais (Dia)'):
        ui.label(f'Registros do dia ({datetime.now().strftime("%d/%m/%Y")})').classes('text-lg font-medium')
        with ui.row().classes('w-full'):
            lobby_table = ui.table(
                columns=[
                    {'name': 'hora', 'label': 'Hora', 'field': 'hora'},
                    {'name': 'nome', 'label': 'Nome', 'field': 'nome'},
                    {'name': 'evento', 'label': 'Evento', 'field': 'evento'},
                    {'name': 'uid', 'label': 'UID', 'field': 'uid'},
                ],
                rows=[],
            ).classes('w-1/2')

        def atualizar_lobby_table():
            hoje = datetime.now().strftime("%Y-%m-%d")
            items = []
            for uid, dias in config.registros.items():
                nome = config.funcionarios.get(uid, uid)
                dia = dias.get(hoje, {})
                for ev in config.EVENTOS:
                    if ev in dia:
                        items.append({'hora': dia[ev], 'nome': nome, 'evento': ev.replace('_', ' '), 'uid': uid})
            items.sort(key=lambda r: r['hora'])
            lobby_table.rows = items
            lobby_table.update()

        ui.button('Atualizar', on_click=atualizar_lobby_table)
        atualizar_lobby_table()

    # ====== ABA EXPORTAR EXCEL ======
    with ui.tab_panel('Exportar Excel'):
        ui.label('Exportar registros para Excel (.xlsx)').classes('text-lg font-medium')
        def coletar_meses_disponiveis():
            """Retorna (options_dict, default_iso):
            options_dict = { 'YYYY-MM': 'MM/YYYY' }, ordenado do mais recente para o mais antigo."""
            meses = set()
            for _uid, dias in config.registros.items():
                for data_iso in dias.keys():
                    if len(data_iso) >= 7:
                        meses.add(data_iso[:7])
            if not meses:
                atual_iso = datetime.now().strftime("%Y-%m")
                return {atual_iso: datetime.strptime(atual_iso, "%Y-%m").strftime("%m/%Y")}, atual_iso

            ordenados = sorted(meses, reverse=True)
            options = {m: datetime.strptime(m, "%Y-%m").strftime("%m/%Y") for m in ordenados}
            return options, ordenados[0]

        mes_options, mes_default = coletar_meses_disponiveis()
        mes_select = ui.select(options=mes_options, value=mes_default, label='Mês (MM/YYYY)').classes('min-w-[200px]')
        abrir_btn = ui.button('Abrir no Excel', icon='folder_open', on_click=lambda: abrir_no_excel())
        abrir_btn.disable()
        
        def abrir_no_excel():
            import os, subprocess, sys
            global last_export_path
            if not last_export_path or not os.path.exists(last_export_path):
                ui.notify('Nenhum arquivo exportado ainda ou arquivo não encontrado.', type='warning')
                return
            try:
                if sys.platform.startswith("win"):
                    os.startfile(last_export_path)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", last_export_path])
                else:
                    subprocess.Popen(["xdg-open", last_export_path])
                ui.notify(f'Abrindo: {os.path.basename(last_export_path)}', type='positive')
            except Exception as e:
                ui.notify(f'Erro ao abrir: {e}', type='negative')

        def exportar_xlsx_ui():
            import os, sys, subprocess
            global last_export_path
            mes_iso = (mes_select.value or '').strip()   # já é 'YYYY-MM'
            try:
                caminho = export_excel.exportar_mes_xlsx(mes_iso, config.funcionarios, config.registros, config.EVENTOS)
                ui.notify(f'Arquivo gerado: {caminho}', type='positive')

                # dispara o download pelo navegador
                ui.download(caminho)

                # guarda caminho absoluto para o botão "Abrir no Excel"
                last_export_path = os.path.abspath(caminho)
                abrir_btn.enable()  # habilita o botão agora que existe um arquivo

            except Exception as e:
                ui.notify(f'Erro: {e}', type='negative')

        ui.button('Exportar mês (xlsx)', on_click=exportar_xlsx_ui, color='primary')
        ui.label('Gera 1 arquivo por mês, com 1 aba por funcionário + aba Resumo. "Horas" no formato [h]:mm.')

# ====== Downloads (estáticos) ======
app.add_static_files('/data', '.')   # /data/funcionarios.json, /data/registros.json e /data/export/...

# ===================== Timers e Handlers =====================
def push_log(texto, tipo="info"):
    if tipo == "ok":
        ui.notify(texto, type='positive', position='top-right')
    elif tipo == "err":
        ui.notify(texto, type='negative', position='top-right')

def ui_tick():
    # status destacado do canto superior direito
    if config.serial_connected:
        status_label.text = f'CONECTADO ({config.PORTA_ATUAL})'
        status_label.classes(replace='text-white bg-green-600 px-3 py-1 rounded font-bold shadow')
    else:
        status_label.text = 'DESCONECTADO'
        status_label.classes(replace='text-white bg-red-600 px-3 py-1 rounded font-bold shadow pulse')

    def _refresh_views():
        try:
            atualizar_tabela_batidas_por_func()
        except:
            pass
        try:
            atualizar_lobby_table()
        except:
            pass
        try:
            atualizar_datas_select()
        except:
            pass
        try:
            new_opts, new_default = coletar_meses_disponiveis()
            mes_select.options = new_opts
            if mes_select.value not in new_opts:
                mes_select.value = new_default
            mes_select.update()
        except Exception as e:
            print(f"[WARN] Falha ao atualizar lista de meses: {e}")

    try:
        while True:
            kind, payload = config.serial_queue.get_nowait()

            if kind == "ok":
                push_log(payload, "ok")
                _refresh_views()

            elif kind == "err":
                push_log(payload, "err")
                _refresh_views()

            elif kind == "log":
                push_log(payload, "info")

            elif kind == "uid_captured":
                uid_in.value = payload
                uid_in.update()
                ui.notify(f'UID capturado: {payload}', type='positive')

            elif kind == "update_data": 
                push_log("Dados de registro atualizados. Aplicando atualizações na UI.", "info")
                _refresh_views() 

    except queue.Empty:
        pass

ui.timer(0.2, ui_tick)
ui.run(title='Ponto NFC', reload=False)

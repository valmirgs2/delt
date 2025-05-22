import streamlit as st
import math
import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from datetime import datetime, timedelta
import time
import random # Para simular dados da Ecowitt
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# --- Simulação do Firestore (substitua pela integração real) ---
if 'db_historico' not in st.session_state:
    st.session_state.db_historico = []

def salvar_dados_no_firestore_simulado(dados):
    st.session_state.db_historico.append(dados)
    max_historico = 100 # Mantém os últimos 100 registros no total
    if len(st.session_state.db_historico) > max_historico:
        st.session_state.db_historico = st.session_state.db_historico[-max_historico:]

def carregar_historico_do_firestore_simulado():
    return sorted(st.session_state.db_historico, key=lambda x: x['timestamp'], reverse=True)

# --- FUNÇÕES DE CÁLCULO ATUALIZADAS ---
def calcular_temperatura_bulbo_umido_stull(t_bs, rh):
    term1_factor = (rh + 8.313659)**0.5
    term1 = t_bs * math.atan(0.151977 * term1_factor)
    term2 = math.atan(t_bs + rh)
    term3 = math.atan(rh - 1.676331)
    term4_factor1 = rh**1.5
    term4_factor2 = math.atan(0.023101 * rh)
    term4 = 0.00391838 * term4_factor1 * term4_factor2
    constante_final = 4.686035
    t_w = term1 + term2 - term3 + term4 - constante_final
    return t_w

def calcular_delta_t_e_condicao(t_bs, rh):
    if not (0 <= rh <= 100):
        return None, None, "Erro: Umidade Relativa fora da faixa (0-100%).", None, None, None
    if not (0 <= t_bs <= 50):
        return None, None, f"Erro: Temperatura do Ar ({t_bs}°C) fora da faixa de cálculo (0-50°C).", None, None, None
    try:
        t_w = calcular_temperatura_bulbo_umido_stull(t_bs, rh)
        delta_t = t_bs - t_w

        ponto_orvalho = t_bs - ((100 - rh) / 5.0)
        sensacao_termica = t_bs + 0.3 * (rh/100 * 6.105 * math.exp(17.27 * t_bs / (237.7 + t_bs)) - 10)
        if rh < 50 and t_bs > 25 : sensacao_termica = t_bs + (t_bs-25)/5
        elif rh > 70 and t_bs > 25: sensacao_termica = t_bs + (rh-70)/10 + (t_bs-25)/3

        condicao_texto = "-"
        descricao_condicao = ""
        # NOVAS CONDIÇÕES E DESCRIÇÕES PARA DELTA T
        if delta_t < 2:
            condicao_texto = "ARRISCADA"
            descricao_condicao = "Risco elevado de deriva e escorrimento (Delta T < 2°C)."
        elif delta_t > 10: # Prioridade maior que a faixa 8-10
            condicao_texto = "INADEQUADA"
            descricao_condicao = "Risco crítico de evaporação das gotas (Delta T > 10°C)."
        elif 2 <= delta_t <= 8:
            condicao_texto = "ADEQUADA"
            descricao_condicao = "Condições ideais para pulverização (2°C ≤ Delta T ≤ 8°C)."
        elif 8 < delta_t <= 10: # Esta condição vem depois de >10 e <2
            condicao_texto = "ARRISCADA"
            descricao_condicao = f"Condição limite (Delta T {delta_t:.1f}°C). Risco de evaporação."
        else: # Caso algo inesperado
            condicao_texto = "VERIFICAR"
            descricao_condicao = f"Valor de Delta T ({delta_t:.1f}°C) requer atenção."


        return t_w, delta_t, condicao_texto, descricao_condicao, ponto_orvalho, sensacao_termica
    except Exception as e:
        return None, None, f"Erro no cálculo: {e}", None, None, None

@st.cache_data(ttl=600) # Cache do ícone
def carregar_icone(url_icone):
    try:
        response_icone = requests.get(url_icone, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        response_icone.raise_for_status()
        content_type_icone = response_icone.headers.get('content-type', '').lower()
        if not (content_type_icone.startswith('image/png') or \
                content_type_icone.startswith('image/jpeg') or \
                content_type_icone.startswith('image/gif') or \
                content_type_icone.startswith('image/webp')):
            st.warning(f"URL do ícone não é imagem (Content-Type: {content_type_icone}).")
            return None
        return Image.open(BytesIO(response_icone.content)).convert("RGBA")
    except Exception as e:
        print(f"Erro ao carregar ícone: {e}")
        st.warning(f"Não foi possível carregar o ícone de {url_icone}.")
        return None

# --- FUNÇÃO PARA DESENHAR PONTO E ÍCONE NO GRÁFICO (COM COORDENADAS PRECISAS E HISTÓRICO) ---
def desenhar_grafico_com_pontos_e_linhas(imagem_base_pil, pontos_historico, url_icone_alvo, temp_atual=None, rh_atual=None):
    if imagem_base_pil is None: return None
    img_processada = imagem_base_pil.copy()
    draw = ImageDraw.Draw(img_processada)
    icone_alvo_pil = carregar_icone(url_icone_alvo)

    temp_min_grafico, temp_max_grafico = 0.0, 50.0
    pixel_x_min_temp, pixel_x_max_temp = 198, 880
    rh_min_grafico, rh_max_grafico = 10.0, 100.0
    pixel_y_min_rh, pixel_y_max_rh = 650, 108 # Y_min_rh (para 10%) é pixel maior, Y_max_rh (para 100%) é pixel menor

    coordenadas_pixels_historico = []

    todos_os_pontos_para_plotar = list(pontos_historico) # Copia para não modificar a original
    if temp_atual is not None and rh_atual is not None:
         # Adiciona o ponto atual ao final para ser o último desenhado e conectado
        todos_os_pontos_para_plotar.append({'temperature_c': temp_atual, 'humidity_percent': rh_atual, 'atual': True})

    for ponto_data in todos_os_pontos_para_plotar:
        temp_ponto = ponto_data.get('temperature_c')
        rh_ponto = ponto_data.get('humidity_percent')

        if temp_ponto is not None and rh_ponto is not None:
            plotar_temp = max(temp_min_grafico, min(temp_ponto, temp_max_grafico))
            plotar_rh = max(rh_min_grafico, min(rh_ponto, rh_max_grafico))

            range_temp_grafico = temp_max_grafico - temp_min_grafico
            percent_temp = (plotar_temp - temp_min_grafico) / range_temp_grafico if range_temp_grafico != 0 else 0
            pixel_x = int(pixel_x_min_temp + percent_temp * (pixel_x_max_temp - pixel_x_min_temp))

            range_rh_grafico = rh_max_grafico - rh_min_grafico
            percent_rh = (plotar_rh - rh_min_grafico) / range_rh_grafico if range_rh_grafico != 0 else 0
            pixel_y = int(pixel_y_min_rh - percent_rh * (pixel_y_min_rh - pixel_y_max_rh))
            
            coordenadas_pixels_historico.append({'x': pixel_x, 'y': pixel_y, 'atual': ponto_data.get('atual', False)})

    # Desenhar linhas conectando os pontos históricos
    for i in range(1, len(coordenadas_pixels_historico)):
        p_anterior = coordenadas_pixels_historico[i-1]
        p_atual_coord = coordenadas_pixels_historico[i]
        draw.line([(p_anterior['x'], p_anterior['y']), (p_atual_coord['x'], p_atual_coord['y'])], fill="rgba(0,0,255,100)", width=2) # Linha azul semi-transparente

    # Desenhar ícones nos pontos
    if icone_alvo_pil:
        tamanho_icone_base = 30 # Reduzido para não poluir muito
        novo_tamanho_icone = int(tamanho_icone_base * 1.0) # Ajuste o tamanho se necessário
        tamanho_icone = (novo_tamanho_icone, novo_tamanho_icone)
        icone_redimensionado = icone_alvo_pil.resize(tamanho_icone, Image.Resampling.LANCZOS)

        for i, coord_pixel in enumerate(coordenadas_pixels_historico):
            pos_x_icone = coord_pixel['x'] - tamanho_icone[0] // 2
            pos_y_icone = coord_pixel['y'] - tamanho_icone[1] // 2
            
            # Destacar o ponto atual (opcional, pode ser com cor de linha diferente ou ícone maior)
            # if coord_pixel.get('atual', False):
            #     # Poderia usar um ícone diferente ou desenhar um círculo maior ao redor
            #     draw.ellipse([(coord_pixel['x'] - 10, coord_pixel['y'] - 10),
            #                   (coord_pixel['x'] + 10, coord_pixel['y'] + 10)],
            #                  outline="blue", width=2)
            
            img_processada.paste(icone_redimensionado, (pos_x_icone, pos_y_icone), icone_redimensionado)
            
            # Adicionar um pequeno número para indicar a ordem (opcional)
            # try:
            #     font = ImageFont.truetype("arial.ttf", 10) # Requer fonte instalada
            # except IOError:
            #     font = ImageFont.load_default()
            # draw.text((pos_x_icone + tamanho_icone[0], pos_y_icone), str(i+1), fill="black", font=font)


    return img_processada


# --- LÓGICA DA APLICAÇÃO STREAMLIT ---
st.set_page_config(page_title="Estação Meteorológica - BASE AGRO", layout="wide")
st.title("🌦️ Estação Meteorológica - BASE AGRO")

if 'last_update_time' not in st.session_state: st.session_state.last_update_time = datetime.min
if 'dados_atuais' not in st.session_state: st.session_state.dados_atuais = None
if 'imagem_grafico_atual' not in st.session_state: st.session_state.imagem_grafico_atual = None

url_grafico_base = "https://i.postimg.cc/zXZpjrnd/Screenshot-20250520-192948-Drive.jpg"
url_icone_localizacao = "https://estudioweb.com.br/wp-content/uploads/2023/02/Emoji-Alvo-png.png"
INTERVALO_ATUALIZACAO_MINUTOS = 5
MAX_PONTOS_GRAFICO_PRINCIPAL = 10 # Número de pontos históricos no gráfico principal

@st.cache_data(ttl=3600)
def carregar_imagem_base(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        img = Image.open(BytesIO(response.content)).convert("RGBA")
        return img
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao baixar a imagem base do gráfico: {e}")
        return None

imagem_base_pil = carregar_imagem_base(url_grafico_base)
if imagem_base_pil is None:
    st.error("A imagem de fundo do gráfico não pôde ser carregada. O aplicativo pode não funcionar corretamente.")

def buscar_dados_ecowitt_simulado():
    time.sleep(0.2) # Reduzido para testes mais rápidos
    temp = round(random.uniform(15, 35), 1) # Faixa mais comum para teste
    umid = round(random.uniform(30, 90), 1) # Faixa mais comum
    vento_vel = round(random.uniform(0, 20), 1)
    vento_raj = round(vento_vel + random.uniform(0, 15), 1)
    pressao = round(random.uniform(1000, 1025), 1)
    direcoes_vento = ["N", "NE", "L", "SE", "S", "SO", "O", "NO"]
    vento_dir = random.choice(direcoes_vento)
    return {
        "temperature_c": temp, "humidity_percent": umid,
        "wind_speed_kmh": vento_vel, "wind_gust_kmh": vento_raj,
        "pressure_hpa": pressao, "wind_direction": vento_dir,
        # Adicionando outros campos que podem estar faltando para consistência
        "altitude_m": 314, "uv_index": random.randint(0,11),
        "luminosity_lux": random.randint(1000, 80000), "solar_radiation_wm2": random.randint(50,900)
    }

def atualizar_dados_estacao():
    dados_ecowitt = buscar_dados_ecowitt_simulado()
    if dados_ecowitt:
        temp_ar = dados_ecowitt["temperature_c"]
        umid_rel = dados_ecowitt["humidity_percent"]
        t_w, delta_t, condicao, desc_condicao, ponto_orvalho, sensacao_termica = calcular_delta_t_e_condicao(temp_ar, umid_rel)

        if delta_t is not None: # Checar se delta_t foi calculado (não None)
            dados_para_salvar = {
                "timestamp": datetime.now().isoformat(), "temperature_c": temp_ar,
                "humidity_percent": umid_rel,
                "wet_bulb_c": round(t_w, 2) if t_w is not None else None,
                "delta_t_c": round(delta_t, 2), "condition_text": condicao,
                "condition_description": desc_condicao,
                "dew_point_c": round(ponto_orvalho,1) if ponto_orvalho is not None else None,
                "feels_like_c": round(sensacao_termica,1) if sensacao_termica is not None else None,
                **dados_ecowitt
            }
            salvar_dados_no_firestore_simulado(dados_para_salvar)
            st.session_state.dados_atuais = dados_para_salvar

            if imagem_base_pil:
                historico_recente_para_grafico = carregar_historico_do_firestore_simulado()
                # Pegar os últimos N pontos, mas o mais recente é o 'dados_atuais', não incluído ainda no histórico_recente se for a primeira vez
                # A função desenhar_grafico_com_pontos_e_linhas agora recebe o ponto atual separadamente ou como parte da lista
                
                pontos_plot = sorted(st.session_state.db_historico, key=lambda x: x['timestamp'], reverse=False) # Do mais antigo ao mais novo
                pontos_plot = pontos_plot[-(MAX_PONTOS_GRAFICO_PRINCIPAL-1):] # Pega os N-1 mais recentes (sem o atual)
                
                # O ponto atual é o último.
                st.session_state.imagem_grafico_atual = desenhar_grafico_com_pontos_e_linhas(
                    imagem_base_pil,
                    pontos_plot, # Passa a lista de históricos (sem o atual ainda)
                    url_icone_localizacao,
                    temp_ar, # Passa o atual explicitamente
                    umid_rel
                )
            st.session_state.last_update_time = datetime.now()
            return True
        else:
            st.error(f"Erro no cálculo Delta T: {condicao}") # condicao aqui é a msg de erro
            # Salvar dados mesmo com erro de cálculo para histórico
            dados_erro = {
                "timestamp": datetime.now().isoformat(), "temperature_c": temp_ar,
                "humidity_percent": umid_rel, "wet_bulb_c": None, "delta_t_c": None,
                "condition_text": "ERRO CÁLCULO", "condition_description": condicao, **dados_ecowitt
            }
            salvar_dados_no_firestore_simulado(dados_erro) # Salva o erro
            st.session_state.dados_atuais = dados_erro
            # Tenta desenhar apenas o ponto atual no gráfico se houver erro
            if imagem_base_pil:
                 st.session_state.imagem_grafico_atual = desenhar_grafico_com_pontos_e_linhas(
                    imagem_base_pil, [], url_icone_localizacao, temp_ar, umid_rel
                )
            st.session_state.last_update_time = datetime.now()
            return False
    return False

agora_atual = datetime.now()
if st.session_state.last_update_time == datetime.min or \
   st.session_state.last_update_time < (agora_atual - timedelta(minutes=INTERVALO_ATUALIZACAO_MINUTOS)):
    if st.session_state.last_update_time == datetime.min and 'simulacao_info_mostrada' not in st.session_state:
        st.info("Usando dados simulados. Substitua `buscar_dados_ecowitt_simulado` pela sua integração real.")
        st.session_state.simulacao_info_mostrada = True
    if atualizar_dados_estacao():
        if 'running_first_time' not in st.session_state:
            st.session_state.running_first_time = True
            st.rerun() # Rerun para mostrar o primeiro ponto
    # else: # Não precisa de st.rerun em caso de falha na atualização automática


st.caption(f"Última atualização dos dados: {st.session_state.last_update_time.strftime('%d/%m/%Y %H:%M:%S') if st.session_state.last_update_time > datetime.min else 'Aguardando primeira atualização...'}")
st.markdown("---")

col_dados_estacao, col_grafico_delta_t = st.columns([1.2, 1.5]) # Ajuste conforme necessário

with col_dados_estacao:
    st.subheader("Estação Meteorológica (Dados Atuais)")
    dados = st.session_state.dados_atuais
    if dados:
        st.markdown("##### 🌡️ Temperatura e Umidade")
        col_temp1, col_temp2 = st.columns(2)
        with col_temp1:
            st.metric(label="Temperatura do Ar", value=f"{dados.get('temperature_c', '-'):.1f} °C")
            st.metric(label="Ponto de Orvalho", value=f"{dados.get('dew_point_c', '-'):.1f} °C" if dados.get('dew_point_c') is not None else "- °C")
        with col_temp2:
            st.metric(label="Umidade Relativa", value=f"{dados.get('humidity_percent', '-'):.1f} %")
            st.metric(label="Sensação Térmica", value=f"{dados.get('feels_like_c', '-'):.1f} °C" if dados.get('feels_like_c') is not None else "- °C")

        st.markdown("##### 🌱 Delta T")
        condicao_atual_texto = dados.get('condition_text', '-')
        desc_condicao_atual = dados.get('condition_description', 'Aguardando dados...')
        
        # NOVAS CORES PARA AS CONDIÇÕES DELTA T
        cor_fundo_condicao = "lightgray"; cor_texto_condicao = "black"
        if condicao_atual_texto == "ARRISCADA": cor_fundo_condicao = "#FFC107"; cor_texto_condicao = "#332701" # Amarelo
        elif condicao_atual_texto == "ADEQUADA": cor_fundo_condicao = "#28A745"; cor_texto_condicao = "white" # Verde
        elif condicao_atual_texto == "INADEQUADA": cor_fundo_condicao = "#DC3545"; cor_texto_condicao = "white" # Vermelho
        elif condicao_atual_texto == "ERRO CÁLCULO": cor_fundo_condicao = "#F8D7DA"; cor_texto_condicao = "#721C24"
        
        delta_t_val_num = dados.get('delta_t_c', None)
        delta_t_display_val = f"{delta_t_val_num:.2f}" if delta_t_val_num is not None else "-"

        st.markdown(f"""
        <div style='text-align: center; margin-bottom: 10px;'>
            <span style='font-size: 1.1em; font-weight: bold;'>Valor Delta T:</span><br>
            <span style='font-size: 2.2em; font-weight: bold; color: {cor_fundo_condicao};'>{delta_t_display_val} °C</span>
        </div> """, unsafe_allow_html=True)

        st.markdown(f"""
        <div style='background-color: {cor_fundo_condicao}; color: {cor_texto_condicao}; padding: 10px; border-radius: 5px; text-align: center; margin-bottom: 5px;'>
            <strong style='font-size: 1.1em;'>Condição Delta T: {condicao_atual_texto}</strong>
        </div>
        <p style='text-align: center; font-size: 0.85em; color: #555;'>{desc_condicao_atual}</p>
        """, unsafe_allow_html=True)
        st.markdown("---")

        st.markdown("##### 💨 Vento e Pressão")
        # ... (código do vento e pressão permanece o mesmo)
        col_vento1, col_vento2 = st.columns(2)
        vento_velocidade_atual = dados.get('wind_speed_kmh', 0)
        condicao_vento_texto = "-"
        desc_condicao_vento = ""
        cor_fundo_vento = "lightgray"; cor_texto_vento = "black"
        if vento_velocidade_atual <= 3:
            condicao_vento_texto = "ARRISCADO"
            desc_condicao_vento = "Risco de inversão térmica."
            cor_fundo_vento = "#FFE9C5"; cor_texto_vento = "#A76800" # Amarelo claro
        elif 3 < vento_velocidade_atual <= 10:
            condicao_vento_texto = "EXCELENTE"
            desc_condicao_vento = "Condições ideais de vento."
            cor_fundo_vento = "#D4EDDA"; cor_texto_vento = "#155724" # Verde claro
        else:
            condicao_vento_texto = "MUITO PERIGOSO"
            desc_condicao_vento = "Risco de deriva."
            cor_fundo_vento = "#FFD2D2"; cor_texto_vento = "#D8000C" # Vermelho claro
        with col_vento1:
            st.metric(label="Vento Médio", value=f"{vento_velocidade_atual:.1f} km/h")
            st.metric(label="Pressão", value=f"{dados.get('pressure_hpa', '-'):.1f} hPa")
        with col_vento2:
            st.metric(label="Rajadas", value=f"{dados.get('wind_gust_kmh', '-'):.1f} km/h")
            st.metric(label="Direção Vento", value=f"{dados.get('wind_direction', '-')}")
        st.markdown(f"""
        <div style='background-color: {cor_fundo_vento}; color: {cor_texto_vento}; padding: 10px; border-radius: 5px; text-align: center; margin-top: 10px; margin-bottom: 5px;'>
            <strong style='font-size: 1.1em;'>Condição do Vento: {condicao_vento_texto}</strong>
        </div>
        <p style='text-align: center; font-size: 0.85em; color: #555;'>{desc_condicao_vento}</p>
        """, unsafe_allow_html=True)
        st.markdown("---")

    else:
        st.info("Aguardando dados da estação para exibir as condições atuais...")

    if st.button("Forçar Atualização Manual Agora", key="btn_atualizar_col1"):
        if atualizar_dados_estacao():
            st.success("Dados atualizados manualmente!")
            st.rerun()
        else:
            st.error("Falha ao atualizar manualmente.")

with col_grafico_delta_t:
    st.subheader("Gráfico Delta T com Histórico Recente")
    imagem_para_exibir = st.session_state.get('imagem_grafico_atual') or imagem_base_pil
    if imagem_para_exibir:
        caption_text = "Gráfico de referência Delta T."
        if st.session_state.get('dados_atuais') and 'timestamp' in st.session_state.dados_atuais:
            try:
                ts_obj = datetime.fromisoformat(st.session_state.dados_atuais['timestamp'])
                caption_text = f"Ponto mais recente: {ts_obj.strftime('%d/%m/%Y %H:%M:%S')}."
                if len(st.session_state.get('db_historico',[])) > 1:
                     caption_text += f" Mostrando os últimos {min(MAX_PONTOS_GRAFICO_PRINCIPAL, len(st.session_state.db_historico))} pontos."
            except: caption_text = "Gráfico de referência Delta T com histórico."
        st.image(imagem_para_exibir, caption=caption_text, use_container_width=True)
    else:
        st.warning("Imagem base do gráfico não disponível.")

st.markdown("---")
st.subheader("Histórico de Dados Delta T (Últimos Registros)")
historico_completo = carregar_historico_do_firestore_simulado()
if historico_completo:
    df_historico = pd.DataFrame(historico_completo)
    if not df_historico.empty and 'timestamp' in df_historico.columns:
        try:
            df_historico['timestamp_dt'] = pd.to_datetime(df_historico['timestamp'])
            df_historico = df_historico.sort_values(by='timestamp_dt', ascending=False)
            
            # Colunas para exibir no histórico de Delta T
            colunas_delta_t_hist = ['timestamp_dt', 'delta_t_c', 'condition_text']
            colunas_presentes_hist = [col for col in colunas_delta_t_hist if col in df_historico.columns]
            df_display_hist = df_historico[colunas_presentes_hist].head(10) # Mostrar últimos 10
            
            novos_nomes_hist = {
                'timestamp_dt': "Data/Hora",
                'delta_t_c': "Delta T (°C)",
                'condition_text': "Condição Delta T"
            }
            df_display_hist = df_display_hist.rename(columns=novos_nomes_hist)
            if "Data/Hora" in df_display_hist.columns:
                df_display_hist["Data/Hora"] = df_display_hist["Data/Hora"].dt.strftime('%d/%m/%Y %H:%M:%S')
            st.dataframe(df_display_hist, use_container_width=True, hide_index=True)
        except Exception as e_pd:
            print(f"Erro ao processar DataFrame do histórico Delta T: {e_pd}")
            st.error("Erro ao formatar histórico Delta T para exibição.")

        # GRÁFICO DE TENDÊNCIAS DELTA T COM CORES (MATPLOTLIB)
        if not df_historico.empty and 'timestamp_dt' in df_historico.columns and 'delta_t_c' in df_historico.columns and len(df_historico) > 1:
            st.subheader("Tendência Delta T com Condições")
            try:
                df_chart = df_historico[['timestamp_dt', 'delta_t_c']].copy()
                df_chart = df_chart.sort_values(by='timestamp_dt', ascending=True).set_index('timestamp_dt')
                df_chart.dropna(subset=['delta_t_c'], inplace=True) # Remover NaNs em delta_t_c

                if len(df_chart) > 1:
                    fig, ax = plt.subplots(figsize=(10, 4)) # Ajuste o tamanho se necessário
                    
                    for i in range(len(df_chart) - 1):
                        y1 = df_chart['delta_t_c'].iloc[i]
                        y2 = df_chart['delta_t_c'].iloc[i+1]
                        x1 = df_chart.index[i]
                        x2 = df_chart.index[i+1]
                        
                        # Usar o valor inicial do segmento para determinar a cor
                        delta_t_val = y1 
                        color = 'gray' # Cor padrão
                        if delta_t_val < 2: color = '#FFC107'  # Amarelo
                        elif delta_t_val > 10: color = '#DC3545' # Vermelho
                        elif 2 <= delta_t_val <= 8: color = '#28A745' # Verde
                        elif 8 < delta_t_val <= 10: color = '#FFC107' # Amarelo
                        
                        ax.plot([x1, x2], [y1, y2], color=color, linestyle='-', linewidth=2, marker='o', markersize=3)

                    ax.set_title('Tendência do Delta T (°C)')
                    ax.set_xlabel('Data/Hora')
                    ax.set_ylabel('Delta T (°C)')
                    ax.grid(True, linestyle=':', alpha=0.7)
                    fig.autofmt_xdate() # Formatação automática das datas no eixo X
                    ax.xaxis.set_major_formatter(mdates.DateFormatter('%d/%m %H:%M'))

                    # Adicionar linhas horizontais para limites críticos de Delta T
                    ax.axhline(2, color='orange', linestyle='--', linewidth=1, label='Limite Inferior Arriscado (2°C)')
                    ax.axhline(8, color='blue', linestyle='--', linewidth=1, label='Limite Superior Adequado (8°C)')
                    ax.axhline(10, color='darkorange', linestyle='--', linewidth=1, label='Limite Superior Arriscado (10°C)')
                    
                    # Criar legenda personalizada para as cores (se necessário, ou usar a legenda das linhas de limite)
                    handles = [
                        plt.Line2D([0], [0], color='#28A745', lw=2, label='Adequada (2-8°C)'),
                        plt.Line2D([0], [0], color='#FFC107', lw=2, label='Arriscada (<2°C ou 8-10°C)'),
                        plt.Line2D([0], [0], color='#DC3545', lw=2, label='Inadequada (>10°C)')
                    ]
                    ax.legend(handles=handles, loc='upper left', fontsize='small')

                    st.pyplot(fig)
                else:
                    st.warning("Dados insuficientes para gerar o gráfico de tendências do Delta T.")
            except Exception as e_chart:
                print(f"Erro ao gerar gráfico de linha do histórico Delta T: {e_chart}")
                st.error(f"Não foi possível gerar o gráfico de tendências do Delta T: {e_chart}")
else:
    st.info("Nenhum histórico de dados encontrado.")

st.markdown("---")
st.markdown("""
**Notas:**
- O gráfico principal agora mostra os últimos """ + str(MAX_PONTOS_GRAFICO_PRINCIPAL) + """ pontos históricos com linhas de conexão.
- O histórico em tabela foca nos dados de Delta T.
- O gráfico de tendência do Delta T possui cores condicionais por segmento.
- **Para uso real, substitua a função `buscar_dados_ecowitt_simulado()` pela sua integração com a API da sua estação Ecowitt.**
- O histórico é armazenado (simulado) e exibido. Para persistência real, integre com um banco de dados.
""")

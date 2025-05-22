import streamlit as st
import math
import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from datetime import datetime, timedelta, time
import pytz
import time as py_time
import random
import pandas as pd
import altair as alt

# --- Timezone Configuration ---
APP_TIMEZONE_STR = "America/Sao_Paulo"
try:
    app_timezone = pytz.timezone(APP_TIMEZONE_STR)
except pytz.exceptions.UnknownTimeZoneError:
    st.error(f"Fuso horário desconhecido: {APP_TIMEZONE_STR}. Usando UTC.")
    app_timezone = pytz.utc

# --- Simulação do Firestore ---
if 'db_historico' not in st.session_state:
    st.session_state.db_historico = []

def salvar_dados_no_firestore_simulado(dados):
    st.session_state.db_historico.append(dados)
    max_historico = 200
    if len(st.session_state.db_historico) > max_historico:
        st.session_state.db_historico = st.session_state.db_historico[-max_historico:]

def carregar_historico_do_firestore_simulado():
    return sorted(st.session_state.db_historico, key=lambda x: x.get('timestamp', ''), reverse=True)

# --- FUNÇÕES DE CÁLCULO ---
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
    if t_bs is None:
        return None, None, "Erro: Temperatura do Ar (t_bs) não fornecida para cálculo.", None, None, None
    if not isinstance(rh, (int, float)) or not (0 <= rh <= 100): # Added type check for rh
        return None, None, "Erro: Umidade Relativa inválida ou fora da faixa (0-100%).", None, None, None
    if not isinstance(t_bs, (int, float)) or not (0 <= t_bs <= 50): # Added type check for t_bs
        return None, None, f"Erro: Temperatura do Ar ({t_bs}°C) inválida ou fora da faixa de cálculo (0-50°C).", None, None, None
    try:
        t_w = calcular_temperatura_bulbo_umido_stull(t_bs, rh)
        delta_t = t_bs - t_w
        ponto_orvalho = t_bs - ((100 - rh) / 5.0)
        sensacao_termica = t_bs
        if rh >= 40:
            e = (rh/100) * 6.105 * math.exp((17.27 * t_bs) / (237.7 + t_bs))
            sensacao_termica = t_bs + 0.33 * e - 0.70 * 0
            if t_bs > 27:
                sensacao_termica = t_bs + 0.3 * ( (rh/100) * 6.105 * math.exp(17.27 * t_bs / (237.7 + t_bs)) - 10)
        if rh < 50 and t_bs > 25 : sensacao_termica = t_bs + (t_bs-25)/5
        elif rh > 70 and t_bs > 25: sensacao_termica = t_bs + (rh-70)/10 + (t_bs-25)/3

        condicao_texto = "-"
        descricao_condicao = ""
        if delta_t < 2:
            condicao_texto = "INADEQUADA"
            descricao_condicao = "Risco elevado de deriva e escorrimento."
        elif delta_t > 10:
            condicao_texto = "ARRISCADA"
            descricao_condicao = "Risco de evaporação excessiva das gotas."
        elif 2 <= delta_t <= 8:
            condicao_texto = "ADEQUADA"
            descricao_condicao = "Condições ideais para pulverização."
        else: # 8 < delta_t <= 10
            condicao_texto = "ATENÇÃO"
            descricao_condicao = f"Condição limite (Delta T {delta_t:.1f}°C)."
        return t_w, delta_t, condicao_texto, descricao_condicao, ponto_orvalho, sensacao_termica
    except Exception as e:
        return None, None, f"Erro no cálculo: {e}", None, None, None

# --- FUNÇÃO PARA DESENHAR PONTO E ÍCONE NO GRÁFICO ---
def desenhar_grafico_com_ponto(imagem_base_pil, temp_para_plotar, rh_usuario, url_icone):
    if imagem_base_pil is None: return None
    img_processada = imagem_base_pil.copy()
    if temp_para_plotar is None or rh_usuario is None: return img_processada

    draw = ImageDraw.Draw(img_processada)
    temp_min_grafico, temp_max_grafico = 0.0, 50.0
    pixel_x_min_temp, pixel_x_max_temp = 198, 880
    rh_min_grafico, rh_max_grafico = 10.0, 100.0
    pixel_y_min_rh, pixel_y_max_rh = 650, 108

    if not (isinstance(temp_para_plotar, (int, float)) and isinstance(rh_usuario, (int, float))):
        return img_processada # Don't plot if data is invalid type

    if not (temp_min_grafico <= temp_para_plotar <= temp_max_grafico):
        # st.warning(f"Temperatura para plotar ({temp_para_plotar}°C) fora da faixa do gráfico. Ponto não desenhado.")
        return img_processada

    plotar_temp = max(temp_min_grafico, min(temp_para_plotar, temp_max_grafico))
    plotar_rh = max(rh_min_grafico, min(rh_usuario, rh_max_grafico))

    range_temp_grafico = temp_max_grafico - temp_min_grafico
    percent_temp = (plotar_temp - temp_min_grafico) / range_temp_grafico if range_temp_grafico != 0 else 0
    pixel_x_usuario = int(pixel_x_min_temp + percent_temp * (pixel_x_max_temp - pixel_x_min_temp))

    range_rh_grafico = rh_max_grafico - rh_min_grafico
    percent_rh = (plotar_rh - rh_min_grafico) / range_rh_grafico if range_rh_grafico != 0 else 0
    pixel_y_usuario = int(pixel_y_min_rh - percent_rh * (pixel_y_min_rh - pixel_y_max_rh))

    raio_ponto = 8; cor_ponto = "red"
    draw.ellipse([(pixel_x_usuario - raio_ponto, pixel_y_usuario - raio_ponto),
                  (pixel_x_usuario + raio_ponto, pixel_y_usuario + raio_ponto)],
                 fill=cor_ponto, outline="black", width=1)
    try:
        response_icone = requests.get(url_icone, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        response_icone.raise_for_status()
        content_type_icone = response_icone.headers.get('content-type', '').lower()
        if not any(ct in content_type_icone for ct in ['image/png', 'image/jpeg', 'image/gif', 'image/webp']):
            st.warning(f"URL do ícone não parece ser uma imagem (Content-Type: {content_type_icone}).")
            return img_processada
        icone_img_original = Image.open(BytesIO(response_icone.content)).convert("RGBA")
        tamanho_icone = (int(35 * 1.25), int(35 * 1.25))
        icone_redimensionado = icone_img_original.resize(tamanho_icone, Image.Resampling.LANCZOS)
        pos_x_icone = pixel_x_usuario - tamanho_icone[0] // 2
        pos_y_icone = pixel_y_usuario - tamanho_icone[1] // 2
        img_processada.paste(icone_redimensionado, (pos_x_icone, pos_y_icone), icone_redimensionado)
    except Exception as e_icon:
        st.warning(f"Não foi possível carregar ou processar o ícone de marcação: {e_icon}")
    return img_processada

# --- LÓGICA DA APLICAÇÃO STREAMLIT ---
st.set_page_config(page_title="Estação Meteorológica BASE AGRO", layout="wide")

# --- Logo and Title ---
logo_url = "https://i.postimg.cc/9F8T5vBk/Whats-App-Image-2025-05-20-at-19-33-48.jpg"

@st.cache_data(ttl=3600)
def load_logo_image(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        logo_image = Image.open(BytesIO(response.content))
        return logo_image
    except Exception as e:
        print(f"Erro ao carregar o logo: {e}") # Log to console
        return None

logo_pil = load_logo_image(logo_url)

if logo_pil:
    col_logo, col_title = st.columns([1, 6]) # Adjust ratios as needed
    with col_logo:
        st.image(logo_pil, width=100) # Adjust width as desired
    with col_title:
        st.title("Estação Meteorológica BASE AGRO")
        st.caption("Monitoramento de condições para pulverização agrícola eficiente e segura.")
else:
    st.title("Estação Meteorológica BASE AGRO") # Fallback if logo fails
    st.caption("Monitoramento de condições para pulverização agrícola eficiente e segura.")


if 'last_update_time' not in st.session_state:
    st.session_state.last_update_time = datetime(1970, 1, 1, tzinfo=app_timezone)
if 'dados_atuais' not in st.session_state: st.session_state.dados_atuais = None
if 'imagem_grafico_atual' not in st.session_state: st.session_state.imagem_grafico_atual = None

url_grafico_base = "https://i.postimg.cc/zXZpjrnd/Screenshot-20250520-192948-Drive.jpg"
url_icone_localizacao = "https://estudioweb.com.br/wp-content/uploads/2023/02/Emoji-Alvo-png.png"
INTERVALO_ATUALIZACAO_MINUTOS = 5

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
# if imagem_base_pil is None: # Error already shown in function
#     st.error("A imagem de fundo do gráfico não pôde ser carregada.")

def buscar_dados_ecowitt_simulado():
    py_time.sleep(0.1) # Reduced sleep for faster interaction if needed
    temp_inferior = round(random.uniform(5, 40), 1) # Narrower, more common range
    umid = round(random.uniform(20, 90), 1) # Narrower, more common range
    temp_superior_offset = random.uniform(-1.0, 2.0) # Max +2°C, Min -1°C vs inferior
    temp_superior = round(temp_inferior + temp_superior_offset, 1)
    temp_superior = max(0, min(temp_superior, 50)) # Ensure it's within calc range

    vento_vel = round(random.uniform(0, 25), 1)
    vento_raj = round(vento_vel + random.uniform(1, 10), 1) # Gusts always a bit higher
    pressao = round(random.uniform(990, 1025), 1) # Common pressure range
    direcoes_vento = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"] # Corrected L to E, SO to SW, O to W, NO to NW
    vento_dir = random.choice(direcoes_vento)
    return {
        "temperature_c": temp_inferior, "humidity_percent": umid,
        "temperature_superior_c": temp_superior,
        "wind_speed_kmh": vento_vel, "wind_gust_kmh": vento_raj,
        "pressure_hpa": pressao, "wind_direction": vento_dir,
        "altitude_m": 314, "uv_index": random.randint(0, 11),
        "luminosity_lux": random.randint(5000, 90000),
        "solar_radiation_wm2": random.randint(50, 1000)
    }

def atualizar_dados_estacao():
    dados_ecowitt = buscar_dados_ecowitt_simulado()
    now_app_tz = datetime.now(app_timezone)

    if dados_ecowitt:
        temp_ar_inferior = dados_ecowitt.get("temperature_c")
        umid_rel = dados_ecowitt.get("humidity_percent")
        temp_ar_superior = dados_ecowitt.get("temperature_superior_c")

        t_w, delta_t, condicao, desc_condicao, ponto_orvalho, sensacao_termica = \
            calcular_delta_t_e_condicao(temp_ar_superior, umid_rel)

        temp_para_plotar_grafico = temp_ar_superior if delta_t is not None else None
        
        dados_completos = {
            "timestamp": now_app_tz.isoformat(),
            **dados_ecowitt, # Spread all ecowitt data first
            "temperature_c": temp_ar_inferior, # Ensure this is specifically lower sensor
            "temperature_superior_c": temp_ar_superior, # And this is superior
            "humidity_percent": umid_rel,
            "wet_bulb_c": round(t_w, 2) if t_w is not None else None,
            "delta_t_c": round(delta_t, 2) if delta_t is not None else None,
            "condition_text": condicao if delta_t is not None else "ERRO CÁLCULO",
            "condition_description": desc_condicao if delta_t is not None else "Falha ao calcular Delta T.",
            "dew_point_c": round(ponto_orvalho,1) if ponto_orvalho is not None else None,
            "feels_like_c": round(sensacao_termica,1) if sensacao_termica is not None else None,
        }

        if delta_t is None: # If calculation failed
             # desc_condicao from calcular_delta_t_e_condicao will contain the specific error
            dados_completos["condition_description"] = desc_condicao
            st.error(f"Falha no cálculo Delta T (usando Temp Sup. {temp_ar_superior}°C): {desc_condicao}")


        salvar_dados_no_firestore_simulado(dados_completos)
        st.session_state.dados_atuais = dados_completos
        if imagem_base_pil:
            st.session_state.imagem_grafico_atual = desenhar_grafico_com_ponto(
                imagem_base_pil, temp_para_plotar_grafico, umid_rel, url_icone_localizacao
            )
        st.session_state.last_update_time = now_app_tz
        return delta_t is not None # Return True if calculation was successful
    else:
        st.error("Não foi possível obter os dados da estação Ecowitt (simulado).")
        return False

agora_atual_app_tz = datetime.now(app_timezone)
if st.session_state.last_update_time.year == 1970 or \
   st.session_state.last_update_time < (agora_atual_app_tz - timedelta(minutes=INTERVALO_ATUALIZACAO_MINUTOS)):
    if st.session_state.last_update_time.year == 1970 and 'simulacao_info_mostrada' not in st.session_state:
        # This message is now removed as per user request to not show it.
        # st.info("Usando dados simulados...")
        st.session_state.simulacao_info_mostrada = True # Still track it was shown once
    atualizar_dados_estacao()


last_update_display = 'Aguardando primeira atualização...'
if st.session_state.last_update_time.year > 1970:
    # Changed time format here
    last_update_display = st.session_state.last_update_time.strftime('%d/%m/%Y %H:%M:%S')
st.caption(f"Última atualização dos dados: {last_update_display} (Horário Local: {APP_TIMEZONE_STR})")
st.markdown("---")

st.subheader("Condições Atuais da Estação")
dados = st.session_state.dados_atuais
if dados:
    st.markdown("##### 🌡️ Temperatura e Umidade")
    col_t1, col_t2 = st.columns(2)
    with col_t1:
        st.metric(label="Temp. Ar (Inferior)", value=f"{dados.get('temperature_c', '-'):.1f} °C" if dados.get('temperature_c') is not None else "- °C")
        st.metric(label="Ponto de Orvalho", value=f"{dados.get('dew_point_c', '-'):.1f} °C" if dados.get('dew_point_c') is not None else "- °C")
    with col_t2:
        st.metric(label="Umidade Relativa", value=f"{dados.get('humidity_percent', '-'):.1f} %" if dados.get('humidity_percent') is not None else "- %")
        st.metric(label="Sensação Térmica", value=f"{dados.get('feels_like_c', '-'):.1f} °C" if dados.get('feels_like_c') is not None else "- °C")

    if dados.get('temperature_superior_c') is not None:
        st.metric(label="Temp. Ar (Superior)", value=f"{dados.get('temperature_superior_c'):.1f} °C",
                  help="Esta temperatura é usada para o cálculo do Delta T e seus derivados.")
    st.markdown("---") # Separator before Delta T display based on superior temp

    # Delta T section title removed as per request ("🌱 Delta T")
    # Values displayed are based on temp_ar_superior
    condicao_atual_texto = dados.get('condition_text', '-')
    desc_condicao_atual = dados.get('condition_description', 'Aguardando dados...')
    cor_fundo_condicao = "lightgray"; cor_texto_condicao = "black"
    if condicao_atual_texto == "INADEQUADA": cor_fundo_condicao = "#FFA500"; cor_texto_condicao = "#FFFFFF"
    elif condicao_atual_texto == "ARRISCADA": cor_fundo_condicao = "#FF0000"; cor_texto_condicao = "#FFFFFF"
    elif condicao_atual_texto == "ADEQUADA": cor_fundo_condicao = "#00CC66"; cor_texto_condicao = "#FFFFFF" # Slightly darker green
    elif condicao_atual_texto == "ATENÇÃO": cor_fundo_condicao = "#FFA500"; cor_texto_condicao = "#FFFFFF"
    elif "ERRO" in str(condicao_atual_texto).upper(): cor_fundo_condicao = "#F8D7DA"; cor_texto_condicao = "#721C24"

    delta_t_val_num = dados.get('delta_t_c', None)
    delta_t_display_val = f"{delta_t_val_num:.2f}" if delta_t_val_num is not None else "-"

    st.markdown(f"""
    <div style='text-align: center; margin-bottom: 10px;'>
        <span style='font-size: 1.1em; font-weight: bold;'>Valor Delta T (Base Temp. Superior):</span><br>
        <span style='font-size: 2.2em; font-weight: bold; color: #007bff;'>{delta_t_display_val} °C</span>
    </div>
    """, unsafe_allow_html=True)
    st.markdown(f"""
    <div style='background-color: {cor_fundo_condicao}; color: {cor_texto_condicao}; padding: 10px; border-radius: 5px; text-align: center; margin-bottom: 5px;'>
        <strong style='font-size: 1.1em;'>Condição Delta T: {condicao_atual_texto}</strong>
    </div>
    <p style='text-align: center; font-size: 0.85em; color: #555;'>{desc_condicao_atual}</p>
    """, unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("##### 💨 Vento e Pressão")
    col_v1, col_v2 = st.columns(2)
    vento_velocidade_atual = dados.get('wind_speed_kmh', 0.0)
    if vento_velocidade_atual is None: vento_velocidade_atual = 0.0

    cond_vento_txt = "-"; desc_cond_vento = ""; bg_vento = "lightgray"; txt_vento = "black"
    if vento_velocidade_atual <= 3:
        cond_vento_txt = "INADEQUADO"; desc_cond_vento = "Risco de inversão térmica (vento fraco)."; bg_vento = "#FFA500"; txt_vento = "#FFFFFF"
    elif 3 < vento_velocidade_atual <= 12: # Adjusted upper limit for "EXCELENTE"
        cond_vento_txt = "EXCELENTE"; desc_cond_vento = "Condições ideais de vento."; bg_vento = "#00CC66"; txt_vento = "#FFFFFF"
    else:
        cond_vento_txt = "MUITO PERIGOSO"; desc_cond_vento = "Risco de deriva (vento forte)."; bg_vento = "#FF0000"; txt_vento = "#FFFFFF"

    with col_v1:
        st.metric(label="Vento Médio", value=f"{vento_velocidade_atual:.1f} km/h")
        st.metric(label="Pressão", value=f"{dados.get('pressure_hpa', '-'):.1f} hPa" if dados.get('pressure_hpa') is not None else "- hPa")
    with col_v2:
        st.metric(label="Rajadas", value=f"{dados.get('wind_gust_kmh', '-'):.1f} km/h" if dados.get('wind_gust_kmh') is not None else "- km/h")
        st.metric(label="Direção Vento", value=f"{dados.get('wind_direction', '-')}")

    st.markdown(f"""
    <div style='background-color: {bg_vento}; color: {txt_vento}; padding:10px; border-radius:5px; text-align:center; margin-top:10px; margin-bottom:5px;'>
        <strong style='font-size:1.1em;'>Condição do Vento: {cond_vento_txt}</strong></div>
    <p style='text-align:center; font-size:0.85em; color:#555;'>{desc_cond_vento}</p>
    """, unsafe_allow_html=True)
    st.markdown("---")

    st.markdown("##### 🌡️ Indicador de Inversão Térmica")
    temp_inf_inv = dados.get('temperature_c'); temp_sup_inv = dados.get('temperature_superior_c'); vento_inv = dados.get('wind_speed_kmh')
    
    inv_cols = st.columns(3)
    inv_cols[0].metric(label="Temp. Inferior", value=f"{temp_inf_inv:.1f}°C" if temp_inf_inv is not None else "N/D")
    inv_cols[1].metric(label="Temp. Superior", value=f"{temp_sup_inv:.1f}°C" if temp_sup_inv is not None else "N/D")
    inv_cols[2].metric(label="Vento Atual", value=f"{vento_inv:.1f} km/h" if vento_inv is not None else "N/D")

    s_inv_txt = "Aguardando..."; d_inv_txt = ""; bg_inv = "lightgray"; txt_inv = "black"
    if all(v is not None for v in [temp_inf_inv, temp_sup_inv, vento_inv]):
        if temp_sup_inv < temp_inf_inv:
            s_inv_txt = "APLICAÇÃO LIBERADA"; d_inv_txt = "Sem inversão térmica."; bg_inv = "#00CC66"; txt_inv = "#FFFFFF"
        elif temp_sup_inv > temp_inf_inv:
            if vento_inv < 3:
                s_inv_txt = "INVERSÃO TÉRMICA"; d_inv_txt = "Não aplicar!"; bg_inv = "#FF0000"; txt_inv = "#FFFFFF"
            else:
                s_inv_txt = "CUIDADO!"; d_inv_txt = "Possível inversão (T Sup > T Inf), mas vento >= 3km/h."; bg_inv = "#FFA500"; txt_inv = "#FFFFFF"
        else:
            s_inv_txt = "CONDIÇÃO ESTÁVEL"; d_inv_txt = "Temperaturas iguais. Monitore o vento."
    else:
        d_inv_txt = "Dados insuficientes."

    st.markdown(f"""
    <div style='background-color:{bg_inv}; color:{txt_inv}; padding:10px; border-radius:5px; text-align:center; margin-top:10px; margin-bottom:5px;'>
        <strong style='font-size:1.1em;'>{s_inv_txt}</strong></div>
    <p style='text-align:center; font-size:0.85em; color:#555;'>{d_inv_txt}</p>
    """, unsafe_allow_html=True)
    st.markdown("---")
else:
    st.info("Aguardando dados da estação para exibir as condições atuais...")

if st.button("🔄 Forçar Atualização Manual", key="btn_atualizar_dados", help="Busca novos dados da estação simulada."):
    if atualizar_dados_estacao():
        st.success("Dados atualizados!")
        st.rerun()
    # else: # Error already shown by atualizar_dados_estacao
        # st.error("Falha ao atualizar.")

st.subheader("Gráfico Delta T de Referência")
temp_sup_atual_str = f"{dados.get('temperature_superior_c', 'N/A'):.1f}°C" if dados and dados.get('temperature_superior_c') is not None else "N/A"
umid_atual_str = f"{dados.get('humidity_percent', 'N/A'):.1f}%" if dados and dados.get('humidity_percent') is not None else "N/A"
st.caption(f"Ponto no gráfico (se visível): Temp. Superior {temp_sup_atual_str}, Umidade {umid_atual_str}.")

img_para_exibir = st.session_state.get('imagem_grafico_atual')
if img_para_exibir:
    ts_atual_str = datetime.fromisoformat(dados['timestamp']).astimezone(app_timezone).strftime('%d/%m/%Y %H:%M:%S') if dados and 'timestamp' in dados else "desconhecida"
    st.image(img_para_exibir, caption=f"Ponto plotado para dados de: {ts_atual_str}", use_container_width=True)
elif imagem_base_pil:
    st.image(imagem_base_pil, caption="Gráfico de referência Delta T (aguardando dados para plotar ponto).", use_container_width=True)
else:
    st.warning("Imagem base do gráfico Delta T não pôde ser carregada.")

st.markdown("---")
st.subheader("Histórico de Dados da Estação")
historico_bruto = carregar_historico_do_firestore_simulado()

if historico_bruto:
    df_historico = pd.DataFrame(historico_bruto)
    if not df_historico.empty and 'timestamp' in df_historico.columns:
        try:
            df_historico['timestamp_dt'] = pd.to_datetime(df_historico['timestamp'])
            df_historico['timestamp_dt'] = df_historico['timestamp_dt'].dt.tz_convert(app_timezone)
            df_historico = df_historico.sort_values(by='timestamp_dt', ascending=False)

            st.markdown("##### Últimos Registros")
            cols_hist = ['timestamp_dt', 'temperature_c', 'temperature_superior_c', 'humidity_percent', 'delta_t_c', 'condition_text', 'wind_speed_kmh']
            df_display = df_historico[[col for col in cols_hist if col in df_historico.columns]].head(10).copy()
            
            mapa_nomes = {'timestamp_dt': "Data/Hora",'temperature_c': "T. Inf (°C)",'temperature_superior_c': "T. Sup (°C)",
                          'humidity_percent': "UR (%)",'delta_t_c': "ΔT (°C)",'condition_text': "Cond. ΔT",'wind_speed_kmh': "Vento (km/h)"}
            df_display.rename(columns=mapa_nomes, inplace=True)
            if "Data/Hora" in df_display.columns: # Changed time format here
                df_display["Data/Hora"] = df_display["Data/Hora"].dt.strftime('%d/%m/%Y %H:%M:%S')
            st.dataframe(df_display, use_container_width=True, hide_index=True)
            st.markdown("---")
            st.subheader("Tendências Recentes")

            df_chart_full = df_historico.set_index('timestamp_dt').sort_index()
            opts_intervalo = {"1 Hora": 1,"3 Horas": 3,"12 Horas": 12,"24 Horas": 24,"3 Dias": 72,"7 Dias": 168, "Todo Histórico": None}
            
            intervalo_sel_label = st.radio("Intervalo Gráficos:", list(opts_intervalo.keys()) + ["Personalizado"], horizontal=True, key="sel_intervalo_graf")
            
            df_chart_filt = pd.DataFrame()
            now_filt = datetime.now(app_timezone)

            if intervalo_sel_label == "Personalizado":
                c_start, c_end = st.columns(2)
                min_dt_hist = df_chart_full.index.min().date() if not df_chart_full.empty else (now_filt - timedelta(days=7)).date()
                d_start = c_start.date_input("Início", min_dt_hist, min_value=(now_filt - timedelta(days=730)).date(), max_value=now_filt.date(), key="d_start_pick")
                d_end = c_end.date_input("Fim", now_filt.date(), min_value=d_start, max_value=now_filt.date(), key="d_end_pick")
                s_dt = app_timezone.localize(datetime.combine(d_start, time.min))
                e_dt = app_timezone.localize(datetime.combine(d_end, time.max))
                df_chart_filt = df_chart_full[(df_chart_full.index >= s_dt) & (df_chart_full.index <= e_dt)]
            else:
                horas = opts_intervalo.get(intervalo_sel_label)
                if horas is not None: df_chart_filt = df_chart_full[df_chart_full.index >= (now_filt - timedelta(hours=horas))]
                else: df_chart_filt = df_chart_full
            
            if not df_chart_filt.empty:
                df_altair = df_chart_filt.reset_index()
                common_x_axis = alt.X('timestamp_dt:T', title='Data/Hora', axis=alt.Axis(format='%d/%m %Hh')) # Adjusted axis format

                # Using predicates= keyword for clarity
                delta_t_chart = alt.Chart(df_altair.dropna(subset=['delta_t_c'])).mark_line(point=alt.OverlayMarkDef(size=15), interpolate='monotone').encode(
                    x=common_x_axis,
                    y=alt.Y('delta_t_c:Q', title='Delta T (°C)', scale=alt.Scale(zero=False)),
                    color=alt.condition(
                        alt.LogicalOrPredicate(predicates=[
                            alt.LogicalAndPredicate(predicates=[alt.datum.delta_t_c >= 0, alt.datum.delta_t_c < 2]),
                            alt.LogicalAndPredicate(predicates=[alt.datum.delta_t_c > 8, alt.datum.delta_t_c <= 10])
                        ]),
                        alt.value('orange'),
                        alt.condition(
                            alt.LogicalAndPredicate(predicates=[alt.datum.delta_t_c >= 2, alt.datum.delta_t_c <= 8]),
                            alt.value('#00CC66'), # Matched green
                            alt.condition(alt.datum.delta_t_c > 10, alt.value('red'), alt.value('lightgray'))
                        )
                    ),
                    tooltip=[alt.Tooltip('timestamp_dt:T', title='Data/Hora', format='%d/%m %H:%M'),
                             alt.Tooltip('delta_t_c:Q', title='ΔT (°C)', format='.2f'),
                             alt.Tooltip('condition_text:N', title='Cond. ΔT')]
                ).properties(title='Tendência Delta T (base Temp. Superior)').interactive()
                st.altair_chart(delta_t_chart, use_container_width=True)

                # Simplified charts for brevity
                temp_inf_chart = alt.Chart(df_altair.dropna(subset=['temperature_c'])).mark_line(point=True, color='royalblue').encode(
                    x=common_x_axis, y=alt.Y('temperature_c:Q', title='T. Inf. (°C)'),
                    tooltip=[alt.Tooltip('timestamp_dt:T', format='%d/%m %H:%M'), alt.Tooltip('temperature_c:Q', format='.1f')]
                ).properties(title='Tendência Temp. Ar (Inferior)').interactive()
                st.altair_chart(temp_inf_chart, use_container_width=True)

                if 'temperature_superior_c' in df_altair.columns:
                    temp_sup_chart = alt.Chart(df_altair.dropna(subset=['temperature_superior_c'])).mark_line(point=True, color='orangered').encode(
                        x=common_x_axis, y=alt.Y('temperature_superior_c:Q', title='T. Sup. (°C)'),
                        tooltip=[alt.Tooltip('timestamp_dt:T', format='%d/%m %H:%M'), alt.Tooltip('temperature_superior_c:Q', format='.1f')]
                    ).properties(title='Tendência Temp. Ar (Superior)').interactive()
                    st.altair_chart(temp_sup_chart, use_container_width=True)
            else:
                st.info("Sem dados históricos para o intervalo selecionado.")
        except Exception as e_pd:
            st.error(f"Erro ao formatar histórico ou gerar gráficos: {e_pd}")
            print(f"Pandas/Altair Error: {e_pd}") # Log full error to console
else:
    st.info("Nenhum histórico de dados encontrado.")

st.markdown("---")
st.markdown("""
**Notas:**
- **Delta T:** Calculado com a **Temperatura do Sensor Superior**.
- **Inversão Térmica:** Avaliada comparando T. Inferior, T. Superior e Vento.
- **Horários:** Exibidos no fuso horário local da aplicação (`America/Sao_Paulo`).
- **Simulação:** Para uso real, integre com sua API Ecowitt e um banco de dados.
""", F)

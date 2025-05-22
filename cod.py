import streamlit as st
import math
import requests
from PIL import Image, ImageDraw, ImageFont # ImageFont might not be used in this version
from io import BytesIO
from datetime import datetime, timedelta, time # Added time
import pytz # Added for timezone handling
import time as py_time # Renamed to avoid conflict with datetime.time
import random # Para simular dados da Ecowitt
import pandas as pd # Adicionado para o histórico
import altair as alt # Added for advanced charting

# --- Timezone Configuration ---
APP_TIMEZONE_STR = "America/Sao_Paulo" # UTC-3 (most of Brazil)
try:
    app_timezone = pytz.timezone(APP_TIMEZONE_STR)
except pytz.exceptions.UnknownTimeZoneError:
    st.error(f"Fuso horário desconhecido: {APP_TIMEZONE_STR}. Usando UTC.")
    app_timezone = pytz.utc

# --- Simulação do Firestore (substitua pela integração real) ---
if 'db_historico' not in st.session_state:
    st.session_state.db_historico = []

def salvar_dados_no_firestore_simulado(dados):
    # print(f"Simulando salvamento no Firestore: {dados}")
    st.session_state.db_historico.append(dados)
    max_historico = 100 # Note: for 7-day trends, this might be too small.
    if len(st.session_state.db_historico) > max_historico:
        st.session_state.db_historico = st.session_state.db_historico[-max_historico:]

def carregar_historico_do_firestore_simulado():
    # print("Simulando carregamento do Firestore.")
    # Ensure data is sorted by timestamp if not already guaranteed by insertion order
    return sorted(st.session_state.db_historico, key=lambda x: x.get('timestamp', ''), reverse=True)


# --- FUNÇÕES DE CÁLCULO (No changes from original) ---
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
    if not (0 <= t_bs <= 50): # Adjusted range slightly for typical conditions, Stull might have wider validity
        return None, None, f"Erro: Temperatura do Ar ({t_bs}°C) fora da faixa de cálculo (0-50°C).", None, None, None
    try:
        t_w = calcular_temperatura_bulbo_umido_stull(t_bs, rh)
        delta_t = t_bs - t_w

        ponto_orvalho = t_bs - ((100 - rh) / 5.0)
        # More standard Heat Index / Feels Like for higher RH, simple adjustment for dry
        sensacao_termica = t_bs # Default
        if rh >= 40: # Using a common formula for heat index approximation (simplified)
            e = (rh/100) * 6.105 * math.exp((17.27 * t_bs) / (237.7 + t_bs))
            sensacao_termica = t_bs + 0.33 * e - 0.70 * 0 # Assuming low wind for this part - wind is separate
            # A more common heat index if needed:
            # HI = -42.379 + 2.04901523*T + 10.14333127*RH - .22475541*T*RH - .00683783*T*T - .05481717*RH*RH + .00122874*T*T*RH + .00085282*T*RH*RH - .00000199*T*T*RH*RH
            # For simplicity, sticking to user's existing, slightly modified:
            if t_bs > 27: # Apply only above certain temps
                 sensacao_termica = t_bs + 0.3 * ( (rh/100) * 6.105 * math.exp(17.27 * t_bs / (237.7 + t_bs)) - 10)

        if rh < 50 and t_bs > 25 : sensacao_termica = t_bs + (t_bs-25)/5 # User's original for dry
        elif rh > 70 and t_bs > 25: sensacao_termica = t_bs + (rh-70)/10 + (t_bs-25)/3 # User's original for humid


        condicao_texto = "-"
        descricao_condicao = ""
        if delta_t < 2:
            condicao_texto = "INADEQUADA"
            descricao_condicao = "Risco elevado de deriva e escorrimento."
        elif delta_t > 10:
            condicao_texto = "ARRISCADA" # As per user request, Delta > 10 is "ARRISCADA" (evap)
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


# --- FUNÇÃO PARA DESENHAR PONTO E ÍCONE NO GRÁFICO (No changes from original) ---
def desenhar_grafico_com_ponto(imagem_base_pil, temp_usuario, rh_usuario, url_icone):
    print(f"DEBUG GRÁFICO: Iniciando desenhar_grafico_com_ponto. temp_usuario={temp_usuario}, rh_usuario={rh_usuario}")
    if imagem_base_pil is None:
        print("DEBUG GRÁFICO: Imagem base é None, retornando None.")
        return None

    img_processada = imagem_base_pil.copy()
    draw = ImageDraw.Draw(img_processada)

    temp_min_grafico = 0.0
    temp_max_grafico = 50.0
    pixel_x_min_temp = 198
    pixel_x_max_temp = 880

    rh_min_grafico = 10.0
    rh_max_grafico = 100.0
    pixel_y_min_rh = 650
    pixel_y_max_rh = 108

    if temp_usuario is not None and rh_usuario is not None:
        plotar_temp = max(temp_min_grafico, min(temp_usuario, temp_max_grafico))
        plotar_rh = max(rh_min_grafico, min(rh_usuario, rh_max_grafico))

        range_temp_grafico = temp_max_grafico - temp_min_grafico
        percent_temp = (plotar_temp - temp_min_grafico) / range_temp_grafico if range_temp_grafico != 0 else 0
        pixel_x_usuario = int(pixel_x_min_temp + percent_temp * (pixel_x_max_temp - pixel_x_min_temp))

        range_rh_grafico = rh_max_grafico - rh_min_grafico
        percent_rh = (plotar_rh - rh_min_grafico) / range_rh_grafico if range_rh_grafico != 0 else 0
        pixel_y_usuario = int(pixel_y_min_rh - percent_rh * (pixel_y_min_rh - pixel_y_max_rh))

        raio_ponto = 8
        cor_ponto = "red"
        draw.ellipse([(pixel_x_usuario - raio_ponto, pixel_y_usuario - raio_ponto),
                      (pixel_x_usuario + raio_ponto, pixel_y_usuario + raio_ponto)],
                     fill=cor_ponto, outline="black", width=1)
        try:
            response_icone = requests.get(url_icone, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
            response_icone.raise_for_status()
            content_type_icone = response_icone.headers.get('content-type', '').lower()
            if not (content_type_icone.startswith('image/png') or \
                    content_type_icone.startswith('image/jpeg') or \
                    content_type_icone.startswith('image/gif') or \
                    content_type_icone.startswith('image/webp')):
                st.warning(f"O URL do ícone não parece ser uma imagem direta (Content-Type: {content_type_icone}).")
                return img_processada
            
            icone_img_original = Image.open(BytesIO(response_icone.content)).convert("RGBA")
            tamanho_icone_base = 35
            novo_tamanho_icone = int(tamanho_icone_base * 1.25)
            tamanho_icone = (novo_tamanho_icone, novo_tamanho_icone)
            icone_redimensionado = icone_img_original.resize(tamanho_icone, Image.Resampling.LANCZOS)
            pos_x_icone = pixel_x_usuario - tamanho_icone[0] // 2
            pos_y_icone = pixel_y_usuario - tamanho_icone[1] // 2
            img_processada.paste(icone_redimensionado, (pos_x_icone, pos_y_icone), icone_redimensionado)
        except Exception as e_icon:
            st.warning(f"Não foi possível carregar ou processar o ícone de marcação: {e_icon}")
            print(f"DEBUG ÍCONE: Erro {e_icon}")
    return img_processada

# --- LÓGICA DA APLICAÇÃO STREAMLIT ---
st.set_page_config(page_title="Estação Meteorológica - BASE AGRO", layout="wide")
st.title("🌦️ Estação Meteorológica - BASE AGRO")

# Initialize session state with timezone-aware datetime
if 'last_update_time' not in st.session_state:
    st.session_state.last_update_time = datetime(1970, 1, 1, tzinfo=app_timezone) # Very old, timezone-aware
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
if imagem_base_pil is None:
    st.error("A imagem de fundo do gráfico não pôde ser carregada. O aplicativo pode não funcionar corretamente.")

def buscar_dados_ecowitt_simulado():
    py_time.sleep(0.5) # Use py_time to avoid conflict
    temp = round(random.uniform(0, 45), 1) # Temp range adjusted slightly
    umid = round(random.uniform(10, 95), 1) # RH range adjusted
    vento_vel = round(random.uniform(0, 25), 1) # Wind speed up to 25 km/h
    vento_raj = round(vento_vel + random.uniform(0, 15), 1)
    pressao = round(random.uniform(980, 1030), 1) # Pressure range
    direcoes_vento = ["N", "NE", "L", "SE", "S", "SO", "O", "NO"]
    vento_dir = random.choice(direcoes_vento)
    altitude = 314
    uv_index = random.randint(0, 11)
    luminosidade = random.randint(1000, 100000) # Increased max luminosity
    radiacao_solar = random.randint(0, 1200) # Broader solar radiation
    return {
        "temperature_c": temp, "humidity_percent": umid,
        "wind_speed_kmh": vento_vel, "wind_gust_kmh": vento_raj,
        "pressure_hpa": pressao, "wind_direction": vento_dir, "altitude_m": altitude,
        "uv_index": uv_index, "luminosity_lux": luminosidade, "solar_radiation_wm2": radiacao_solar
    }

def atualizar_dados_estacao():
    print("DEBUG APP: Iniciando atualizar_dados_estacao")
    dados_ecowitt = buscar_dados_ecowitt_simulado()
    now_app_tz = datetime.now(app_timezone)

    if dados_ecowitt:
        temp_ar = dados_ecowitt["temperature_c"]
        umid_rel = dados_ecowitt["humidity_percent"]
        t_w, delta_t, condicao, desc_condicao, ponto_orvalho, sensacao_termica = calcular_delta_t_e_condicao(temp_ar, umid_rel)

        if t_w is not None and delta_t is not None:
            dados_para_salvar = {
                "timestamp": now_app_tz.isoformat(), # Store with timezone
                "temperature_c": temp_ar,
                "humidity_percent": umid_rel,
                "wet_bulb_c": round(t_w, 2),
                "delta_t_c": round(delta_t, 2),
                "condition_text": condicao,
                "condition_description": desc_condicao,
                "dew_point_c": round(ponto_orvalho,1) if ponto_orvalho is not None else None,
                "feels_like_c": round(sensacao_termica,1) if sensacao_termica is not None else None,
                **dados_ecowitt
            }
            salvar_dados_no_firestore_simulado(dados_para_salvar)
            st.session_state.dados_atuais = dados_para_salvar
            if imagem_base_pil:
                st.session_state.imagem_grafico_atual = desenhar_grafico_com_ponto(
                    imagem_base_pil, temp_ar, umid_rel, url_icone_localizacao
                )
            st.session_state.last_update_time = now_app_tz
            return True
        else:
            st.error(f"Erro no cálculo Delta T: {condicao}")
            dados_erro = {
                "timestamp": now_app_tz.isoformat(),
                "temperature_c": temp_ar, "humidity_percent": umid_rel,
                "wet_bulb_c": None, "delta_t_c": None,
                "condition_text": "ERRO CÁLCULO", "condition_description": condicao, **dados_ecowitt
            }
            st.session_state.dados_atuais = dados_erro
            if imagem_base_pil:
                 st.session_state.imagem_grafico_atual = desenhar_grafico_com_ponto(
                    imagem_base_pil, temp_ar, umid_rel, url_icone_localizacao
                )
            st.session_state.last_update_time = now_app_tz
            return False
    else:
        st.error("Não foi possível obter os dados da estação Ecowitt (simulado).")
        return False

agora_atual_app_tz = datetime.now(app_timezone)
# Check if it's initial run or time for update
if st.session_state.last_update_time.year == 1970 or \
   st.session_state.last_update_time < (agora_atual_app_tz - timedelta(minutes=INTERVALO_ATUALIZACAO_MINUTOS)):
    if st.session_state.last_update_time.year == 1970 and 'simulacao_info_mostrada' not in st.session_state:
        st.info("Usando dados simulados. Substitua `buscar_dados_ecowitt_simulado` pela sua integração real com a API Ecowitt.")
        st.session_state.simulacao_info_mostrada = True
    if atualizar_dados_estacao():
        if 'running_first_time' not in st.session_state:
            st.session_state.running_first_time = True
            st.rerun()
    else:
        print(f"DEBUG APP: Tentativa de atualização automática às {agora_atual_app_tz.strftime('%H:%M:%S %Z')} não bem-sucedida.")


# Display last update time
last_update_display = 'Aguardando primeira atualização...'
if st.session_state.last_update_time.year > 1970:
    last_update_display = st.session_state.last_update_time.strftime('%d/%m/%Y %H:%M:%S %Z')
st.caption(f"Última atualização dos dados: {last_update_display}")
st.markdown("---")

col_dados_estacao, col_grafico_delta_t = st.columns([1.2, 1.5])

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
        cor_fundo_condicao = "lightgray"; cor_texto_condicao = "black"
        # Hex colors are solid (0% transparency)
        if condicao_atual_texto == "INADEQUADA": cor_fundo_condicao = "#FFA500"; cor_texto_condicao = "#D8000C" # Light Red
        elif condicao_atual_texto == "ARRISCADA": cor_fundo_condicao = "#FF0000"; cor_texto_condicao = "#B08D00" # Light Yellow/Orange
        elif condicao_atual_texto == "ADEQUADA": cor_fundo_condicao = "#00EE00"; cor_texto_condicao = "#155724" # Light Green
        elif condicao_atual_texto == "ATENÇÃO": cor_fundo_condicao = "#FFE9C5"; cor_texto_condicao = "#A76800" # Light Orange
        elif condicao_atual_texto == "ERRO CÁLCULO": cor_fundo_condicao = "#F8D7DA"; cor_texto_condicao = "#721C24" # Light Pink/Red


        delta_t_val_num = dados.get('delta_t_c', None)
        delta_t_display_val = f"{delta_t_val_num:.2f}" if delta_t_val_num is not None else "-"

        st.markdown(f"""
        <div style='text-align: center; margin-bottom: 10px;'>
            <span style='font-size: 1.1em; font-weight: bold;'>Valor Delta T:</span><br>
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
        col_vento1, col_vento2 = st.columns(2)
        vento_velocidade_atual = dados.get('wind_speed_kmh', 0)

        condicao_vento_texto = "-"
        desc_condicao_vento = ""
        cor_fundo_vento = "lightgray"; cor_texto_vento = "black"

        if vento_velocidade_atual <= 3: # km/h
            condicao_vento_texto = "ARRISCADO"
            desc_condicao_vento = "Risco de inversão térmica (vento muito fraco)."
            cor_fundo_vento = "#FFA500"; cor_texto_vento = "#A76800" # Light Orange
        elif 3 < vento_velocidade_atual <= 10: # Adjusted upper limit slightly based on common recs (e.g. 10-12 km/h)
            condicao_vento_texto = "EXCELENTE"
            desc_condicao_vento = "Condições ideais de vento."
            cor_fundo_vento = "#00EE00"; cor_texto_vento = "#155724" # Light Green
        else: # > 10 km/h
            condicao_vento_texto = "MUITO PERIGOSO"
            desc_condicao_vento = "Risco de deriva (vento forte)."
            cor_fundo_vento = "#FF0000"; cor_texto_vento = "#D8000C" # Light Red

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
            st.error("Falha ao atualizar manually.")

with col_grafico_delta_t:
    st.subheader("Gráfico Delta T")
    imagem_para_exibir = st.session_state.get('imagem_grafico_atual') or imagem_base_pil

    if imagem_para_exibir:
        caption_text = "Gráfico de referência Delta T"
        if st.session_state.get('dados_atuais') and 'timestamp' in st.session_state.dados_atuais:
            try:
                # Timestamp is already an ISO string with offset, parse directly
                ts_obj = datetime.fromisoformat(st.session_state.dados_atuais['timestamp'])
                # Display in app's timezone
                caption_text = f"Ponto indicativo para dados de: {ts_obj.astimezone(app_timezone).strftime('%d/%m/%Y %H:%M:%S %Z')}"
            except Exception as e:
                 caption_text = f"Ponto indicativo para dados de: {st.session_state.dados_atuais['timestamp']} (erro formatando: {e})"
        st.image(imagem_para_exibir, caption=caption_text, use_container_width=True)
    else:
        st.warning("Imagem base do gráfico não disponível.")

st.markdown("---")
st.subheader("Histórico de Dados da Estação")
historico_bruto = carregar_historico_do_firestore_simulado()

if historico_bruto:
    df_historico = pd.DataFrame(historico_bruto)
    if not df_historico.empty and 'timestamp' in df_historico.columns:
        try:
            # Convert 'timestamp' (ISO string with offset) to timezone-aware datetime objects
            df_historico['timestamp_dt'] = pd.to_datetime(df_historico['timestamp'])
            # Ensure they are in the app_timezone for consistent display (though to_datetime should handle offset)
            df_historico['timestamp_dt'] = df_historico['timestamp_dt'].dt.tz_convert(app_timezone)

            df_historico = df_historico.sort_values(by='timestamp_dt', ascending=False)

            st.markdown("##### Últimos Registros")
            colunas_para_exibir = ['timestamp_dt', 'temperature_c', 'humidity_percent', 'delta_t_c', 'condition_text', 'wind_speed_kmh', 'pressure_hpa']
            colunas_presentes = [col for col in colunas_para_exibir if col in df_historico.columns]
            df_display = df_historico[colunas_presentes].head(10)

            novos_nomes_colunas = {
                'timestamp_dt': "Data/Hora", 'temperature_c': "Temp. Ar (°C)",
                'humidity_percent': "Umid. Rel. (%)", 'delta_t_c': "Delta T (°C)",
                'condition_text': "Condição Delta T", 'wind_speed_kmh': "Vento (km/h)",
                'pressure_hpa': "Pressão (hPa)"}
            df_display = df_display.rename(columns=novos_nomes_colunas)

            if "Data/Hora" in df_display.columns:
                 # Format with timezone abbreviation
                df_display["Data/Hora"] = df_display["Data/Hora"].dt.strftime('%d/%m/%Y %H:%M:%S %Z')
            st.dataframe(df_display, use_container_width=True, hide_index=True)

            st.markdown("---")
            st.subheader("Tendências Recentes")

            # Set index for charting
            df_chart_full_history = df_historico.set_index('timestamp_dt').sort_index()

            # Interval Selection
            interval_options_map = {
                "Última 1 Hora": timedelta(hours=1),
                "Últimas 24 Horas": timedelta(days=1),
                "Últimos 7 Dias": timedelta(days=7),
                "Todo o Histórico": None # Special case for all data
            }
            
            st.write("Selecione o intervalo para os gráficos de tendências:")
            interval_choice = st.radio(
                "Intervalo:",
                options=list(interval_options_map.keys()) + ["Intervalo Personalizado"],
                horizontal=True, key="interval_selector"
            )

            now_for_filter = datetime.now(app_timezone)
            df_chart_filtered = pd.DataFrame() # Initialize as empty

            if interval_choice == "Intervalo Personalizado":
                col_start, col_end = st.columns(2)
                default_min_date = (now_for_filter - timedelta(days=7)).date()
                default_max_date = now_for_filter.date()
                if not df_chart_full_history.empty:
                    # Ensure index is tz-aware before taking .date()
                    min_hist_date = df_chart_full_history.index.min().to_pydatetime().astimezone(app_timezone).date()
                    max_hist_date = df_chart_full_history.index.max().to_pydatetime().astimezone(app_timezone).date()
                    default_min_date = min_hist_date
                    # default_max_date remains today or max_hist_date if preferred

                with col_start:
                    start_date_custom = st.date_input(
                        "Data Início",
                        value=default_min_date,
                        min_value= (now_for_filter - timedelta(days=365*2)).date(), # Limit min selectable
                        max_value=now_for_filter.date(), # Max is today
                        key="start_date_picker"
                    )
                with col_end:
                    end_date_custom = st.date_input(
                        "Data Fim",
                        value=default_max_date,
                        min_value=start_date_custom if start_date_custom else default_min_date,
                        max_value=now_for_filter.date(),
                        key="end_date_picker"
                    )
                
                if start_date_custom and end_date_custom:
                    start_dt = app_timezone.localize(datetime.combine(start_date_custom, time.min))
                    end_dt = app_timezone.localize(datetime.combine(end_date_custom, time.max))
                    df_chart_filtered = df_chart_full_history[(df_chart_full_history.index >= start_dt) & (df_chart_full_history.index <= end_dt)]

            else:
                interval_delta = interval_options_map.get(interval_choice)
                if interval_delta is not None:
                    cutoff_time = now_for_filter - interval_delta
                    df_chart_filtered = df_chart_full_history[df_chart_full_history.index >= cutoff_time]
                else: # "Todo o Histórico"
                    df_chart_filtered = df_chart_full_history


            if not df_chart_filtered.empty:
                df_chart_display_altair = df_chart_filtered.reset_index()

                # Chart for Delta T with conditional coloring
                delta_t_chart = alt.Chart(df_chart_display_altair).mark_line(point=True, interpolate='monotone').encode(
                    x=alt.X('timestamp_dt:T', title='Data/Hora', axis=alt.Axis(format='%d/%m %H:%M')),
                    y=alt.Y('delta_t_c:Q', title='Delta T (°C)', scale=alt.Scale(zero=False)),
                    color=alt.condition(
                        alt.LogicalOrPredicate(
                            alt.LogicalAndPredicate(alt.datum.delta_t_c >= 0, alt.datum.delta_t_c < 2), # 0-2 (exclusive of 2 for yellow)
                            alt.LogicalAndPredicate(alt.datum.delta_t_c > 8, alt.datum.delta_t_c <= 10) # 8-10
                        ),
                        alt.value('orange'), # Yellow/Orange
                        alt.condition(
                            alt.LogicalAndPredicate(alt.datum.delta_t_c >= 2, alt.datum.delta_t_c <= 8), # 2-8
                            alt.value('green'),
                            alt.condition(
                                alt.datum.delta_t_c > 10,
                                alt.value('red'),
                                alt.value('lightgray') # Default for values outside specified ranges (e.g., < 0 or errors)
                            )
                        )
                    ),
                    tooltip=[
                        alt.Tooltip('timestamp_dt:T', title='Data/Hora', format='%d/%m/%Y %H:%M'),
                        alt.Tooltip('delta_t_c:Q', title='Delta T (°C)', format='.2f')
                    ]
                ).properties(
                    title='Tendência Delta T'
                ).interactive() # Adds pan and zoom
                st.altair_chart(delta_t_chart, use_container_width=True)

                # Chart for Temperature
                temp_chart = alt.Chart(df_chart_display_altair).mark_line(point=True, color='royalblue').encode(
                    x=alt.X('timestamp_dt:T', title='Data/Hora', axis=alt.Axis(format='%d/%m %H:%M')),
                    y=alt.Y('temperature_c:Q', title='Temp. Ar (°C)', scale=alt.Scale(zero=False)),
                    tooltip=[
                        alt.Tooltip('timestamp_dt:T', title='Data/Hora', format='%d/%m/%Y %H:%M'),
                        alt.Tooltip('temperature_c:Q', title='Temp. (°C)', format='.1f')
                    ]
                ).properties(
                    title='Tendência Temperatura do Ar'
                ).interactive()
                st.altair_chart(temp_chart, use_container_width=True)

                # Chart for Humidity
                humidity_chart = alt.Chart(df_chart_display_altair).mark_line(point=True, color='forestgreen').encode(
                    x=alt.X('timestamp_dt:T', title='Data/Hora', axis=alt.Axis(format='%d/%m %H:%M')),
                    y=alt.Y('humidity_percent:Q', title='Umid. Rel. (%)', scale=alt.Scale(zero=False)),
                    tooltip=[
                        alt.Tooltip('timestamp_dt:T', title='Data/Hora', format='%d/%m/%Y %H:%M'),
                        alt.Tooltip('humidity_percent:Q', title='Umid. (%)', format='.1f')
                    ]
                ).properties(
                    title='Tendência Umidade Relativa'
                ).interactive()
                st.altair_chart(humidity_chart, use_container_width=True)

                # Chart for Wind Speed
                if 'wind_speed_kmh' in df_chart_display_altair.columns:
                    wind_chart = alt.Chart(df_chart_display_altair).mark_line(point=True, color='slategray').encode(
                        x=alt.X('timestamp_dt:T', title='Data/Hora', axis=alt.Axis(format='%d/%m %H:%M')),
                        y=alt.Y('wind_speed_kmh:Q', title='Vento (km/h)', scale=alt.Scale(zero=True)), # Wind can be 0
                        tooltip=[
                            alt.Tooltip('timestamp_dt:T', title='Data/Hora', format='%d/%m/%Y %H:%M'),
                            alt.Tooltip('wind_speed_kmh:Q', title='Vento (km/h)', format='.1f')
                        ]
                    ).properties(
                        title='Tendência Velocidade do Vento'
                    ).interactive()
                    st.altair_chart(wind_chart, use_container_width=True)
            else:
                st.info("Não há dados históricos suficientes para o intervalo selecionado para gerar gráficos de tendências.")

        except Exception as e_pd:
            print(f"Erro ao processar DataFrame do histórico ou gerar gráficos: {e_pd}")
            st.error(f"Erro ao formatar histórico ou gerar gráficos: {e_pd}")
else:
    st.info("Nenhum histórico de dados encontrado.")


st.markdown("---")
st.markdown("""
**Notas:**
- Este aplicativo tenta buscar dados (simulados) de uma estação Ecowitt a cada 5 minutos.
- **Fuso Horário:** Todos os horários são exibidos em UTC-3 (America/Sao_Paulo).
- **Cores de Fundo:** As cores de fundo para as condições são sólidas (0% transparência).
- **Gráficos de Tendência:**
    - Exibem marcadores (pontos) em cada atualização.
    - Permitem a seleção de intervalo (1 Hora, 24 Horas, 7 Dias, Personalizado).
    - O gráfico de Delta T possui indicadores de cor na linha conforme as faixas de risco.
- **Para uso real, substitua a função `buscar_dados_ecowitt_simulado()` pela sua integração com a API da sua estação Ecowitt.**
- O histórico é armazenado (simulado) e exibido. Para persistência real, integre com um banco de dados.
- O limite de histórico simulado é de 100 registros. Para análises de longo prazo (ex: 7 dias), este limite pode ser insuficiente.
""")

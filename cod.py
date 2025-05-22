import streamlit as st
import math
import requests
from PIL import Image, ImageDraw
from io import BytesIO
from datetime import datetime, timedelta, time
import pytz
import time as py_time 
import pandas as pd
import altair as alt

# --- Timezone Configuration ---
APP_TIMEZONE_STR = "America/Sao_Paulo"
try:
    app_timezone = pytz.timezone(APP_TIMEZONE_STR)
except pytz.exceptions.UnknownTimeZoneError:
    st.error(f"Fuso horário desconhecido: {APP_TIMEZONE_STR}. Usando UTC.")
    app_timezone = pytz.utc

# --- Simulação do Firestore (Mantido para histórico) ---
if 'db_historico' not in st.session_state:
    st.session_state.db_historico = []

def salvar_dados_no_firestore_simulado(dados):
    st.session_state.db_historico.append(dados)
    max_historico = 200
    if len(st.session_state.db_historico) > max_historico:
        st.session_state.db_historico = st.session_state.db_historico[-max_historico:]

def carregar_historico_do_firestore_simulado():
    return sorted([item.copy() for item in st.session_state.db_historico], key=lambda x: x.get('timestamp', ''), reverse=True)

# --- FUNÇÕES DE CÁLCULO (Sem alterações) ---
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
        return None, None, "Erro: Temperatura do Ar (Superior) não fornecida para cálculo.", None, None, None
    if not isinstance(rh, (int, float)) or not (0 <= rh <= 100):
        return None, None, "Erro: Umidade Relativa inválida ou fora da faixa (0-100%).", None, None, None
    if not isinstance(t_bs, (int, float)) or not (0 <= t_bs <= 50): # Limite de cálculo
        return None, None, f"Erro: Temp. do Ar (Superior: {t_bs}°C) inválida ou fora da faixa (0-50°C).", None, None, None
    try:
        t_w = calcular_temperatura_bulbo_umido_stull(t_bs, rh)
        delta_t = t_bs - t_w
        ponto_orvalho = t_bs - ((100 - rh) / 5.0)
        sensacao_termica = t_bs # Default
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
            condicao_texto = "INADEQUADA"; descricao_condicao = "Risco elevado de deriva e escorrimento."
        elif delta_t > 10:
            condicao_texto = "ARRISCADA"; descricao_condicao = "Risco de evaporação excessiva das gotas."
        elif 2 <= delta_t <= 8:
            condicao_texto = "ADEQUADA"; descricao_condicao = "Condições ideais para pulverização."
        else: # 8 < delta_t <= 10
            condicao_texto = "ATENÇÃO"; descricao_condicao = f"Condição limite (Delta T {delta_t:.1f}°C)."
        return t_w, delta_t, condicao_texto, descricao_condicao, ponto_orvalho, sensacao_termica
    except Exception as e:
        return None, None, f"Erro interno no cálculo Delta T: {e}", None, None, None

# --- FUNÇÃO PARA DESENHAR PONTO E ÍCONE NO GRÁFICO (Sem alterações) ---
def desenhar_grafico_com_ponto(imagem_base_pil, temp_para_plotar, rh_usuario, url_icone):
    if imagem_base_pil is None: return None
    img_processada = imagem_base_pil.copy()
    if temp_para_plotar is None or rh_usuario is None: return img_processada
    if not (isinstance(temp_para_plotar, (int, float)) and isinstance(rh_usuario, (int, float))): return img_processada

    draw = ImageDraw.Draw(img_processada)
    temp_min_g, temp_max_g = 0.0, 50.0; px_x_min, px_x_max = 198, 880
    rh_min_g, rh_max_g = 10.0, 100.0; px_y_min, px_y_max = 650, 108

    if not (temp_min_g <= temp_para_plotar <= temp_max_g): return img_processada

    plot_temp = max(temp_min_g, min(temp_para_plotar, temp_max_g))
    plot_rh = max(rh_min_g, min(rh_usuario, rh_max_g))

    px_x = int(px_x_min + ((plot_temp - temp_min_g) / (temp_max_g - temp_min_g) if (temp_max_g - temp_min_g) != 0 else 0) * (px_x_max - px_x_min))
    px_y = int(px_y_min - ((plot_rh - rh_min_g) / (rh_max_g - rh_min_g) if (rh_max_g - rh_min_g) != 0 else 0) * (px_y_min - px_y_max))

    raio = 8; cor = "red"
    draw.ellipse([(px_x - raio, px_y - raio), (px_x + raio, px_y + raio)], fill=cor, outline="black", width=1)
    try:
        resp_icone = requests.get(url_icone, timeout=10, headers={'User-Agent': 'Mozilla/5.0'})
        resp_icone.raise_for_status()
        if not any(ct in resp_icone.headers.get('content-type','').lower() for ct in ['png','jpeg','gif','webp']):
            return img_processada
        icone_pil = Image.open(BytesIO(resp_icone.content)).convert("RGBA")
        tamanho_icone = (int(35*1.25), int(35*1.25))
        icone_redim = icone_pil.resize(tamanho_icone, Image.Resampling.LANCZOS)
        img_processada.paste(icone_redim, (px_x - tamanho_icone[0]//2, px_y - tamanho_icone[1]//2), icone_redim)
    except Exception: pass
    return img_processada

# --- FUNÇÕES PARA BUSCAR DADOS REAIS DA ECOWITT (Sem alterações na lógica interna) ---
def convert_deg_to_cardinal(deg):
    if deg is None: return None
    try:
        deg = float(deg)
        dirs = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"] # 8 direções principais
        ix = round(deg / 45) % 8
        return dirs[ix]
    except (ValueError, TypeError):
        return None

def fetch_real_ecowitt_data():
    api_key = st.secrets.get("ECOWITT_API_KEY")
    app_key = st.secrets.get("ECOWITT_APPLICATION_KEY")
    mac_address = st.secrets.get("ECOWITT_MAC_ADDRESS")

    if not all([api_key, app_key, mac_address]):
        st.error("Credenciais da API Ecowitt não configuradas em .streamlit/secrets.toml")
        return None

    params = {
        "application_key": app_key, "api_key": api_key, "mac": mac_address,
        "temp_unitid": "1", "pressure_unitid": "3",
        "wind_speed_unitid": "7", "rainfall_unitid": "12", "call_back": "all",
    }
    api_url = "http://api.ecowitt.net/api/v3/device/real_time"

    try:
        response = requests.get(api_url, params=params, timeout=15)
        response.raise_for_status()
        api_data = response.json()

        if api_data.get("code") == 0 and "data" in api_data:
            device_data = api_data["data"]
            mapped_data = {
                "temperature_c": None, "humidity_percent": None, "temperature_superior_c": None,
                "wind_speed_kmh": None, "wind_gust_kmh": None, "pressure_hpa": None,
                "wind_direction": None, "uv_index": None,
                "solar_radiation_wm2": None, "luminosity_lux": None,
            }

            if "indoor" in device_data:
                indoor_block = device_data["indoor"]
                if "temperature" in indoor_block:
                    mapped_data["temperature_c"] = indoor_block["temperature"].get("value")
            if "pressure" in device_data:
                pressure_block = device_data["pressure"]
                mapped_data["pressure_hpa"] = pressure_block.get("relative", {}).get("value")
                if mapped_data["pressure_hpa"] is None:
                    mapped_data["pressure_hpa"] = pressure_block.get("absolute", {}).get("value")
            if "outdoor" in device_data:
                outdoor_block = device_data["outdoor"]
                if "temperature" in outdoor_block:
                    mapped_data["temperature_superior_c"] = outdoor_block["temperature"].get("value")
                if "humidity" in outdoor_block:
                    mapped_data["humidity_percent"] = outdoor_block["humidity"].get("value")
            if "wind" in device_data:
                wind_block = device_data["wind"]
                if "wind_speed" in wind_block:
                    mapped_data["wind_speed_kmh"] = wind_block["wind_speed"].get("value")
                if "wind_gust" in wind_block:
                    mapped_data["wind_gust_kmh"] = wind_block["wind_gust"].get("value")
                if "wind_direction" in wind_block:
                    wind_dir_deg = wind_block["wind_direction"].get("value")
                    mapped_data["wind_direction"] = convert_deg_to_cardinal(wind_dir_deg)
            if "solar_and_uvi" in device_data:
                solar_uvi_block = device_data["solar_and_uvi"]
                if "solar" in solar_uvi_block:
                    mapped_data["solar_radiation_wm2"] = solar_uvi_block["solar"].get("value")
                    if mapped_data["solar_radiation_wm2"] is not None:
                        try: mapped_data["luminosity_lux"] = float(str(mapped_data["solar_radiation_wm2"])) * 120 
                        except: pass 
                if "uvi" in solar_uvi_block:
                    mapped_data["uv_index"] = solar_uvi_block["uvi"].get("value")
            
            for key in mapped_data.keys():
                if mapped_data.get(key) is not None:
                    try: mapped_data[key] = float(str(mapped_data[key]))
                    except (ValueError, TypeError):
                        if not isinstance(mapped_data[key], str): mapped_data[key] = None
            return mapped_data
        else:
            st.error(f"Erro da API Ecowitt: {api_data.get('msg', 'Resposta inválida')} (Código: {api_data.get('code', 'N/A')})")
            return None
    except requests.exceptions.RequestException as e:
        st.error(f"Erro de conexão com a API Ecowitt: {e}")
        return None
    except Exception as e:
        st.error(f"Erro crítico ao processar dados da API Ecowitt: {e}")
        import traceback; print(f"Erro Crítico: {traceback.format_exc()}")
        return None

# --- LÓGICA DA APLICAÇÃO STREAMLIT ---
@st.cache_data(ttl=3600)
def load_image_from_url(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return Image.open(BytesIO(response.content))
    except Exception as e:
        print(f"Erro ao carregar imagem de {url}: {e}")
        return None

logo_pil = load_image_from_url("https://i.postimg.cc/9F8T5vBk/Whats-App-Image-2025-05-20-at-19-33-48.jpg")
url_grafico_base = "https://i.postimg.cc/zXZpjrnd/Screenshot-20250520-192948-Drive.jpg"
imagem_base_pil = load_image_from_url(url_grafico_base)
if imagem_base_pil: imagem_base_pil = imagem_base_pil.convert("RGBA")

col_logo_main, col_title_main = st.columns([1, 6])
with col_logo_main:
    if logo_pil: st.image(logo_pil, width=100)
with col_title_main:
    st.title("Estação Meteorológica BASE AGRO")
    st.caption("Monitoramento de condições para pulverização agrícola eficiente e segura.")

if 'last_update_time' not in st.session_state: st.session_state.last_update_time = datetime(1970,1,1,tzinfo=app_timezone)
if 'dados_atuais' not in st.session_state: st.session_state.dados_atuais = {}
if 'imagem_grafico_atual' not in st.session_state: st.session_state.imagem_grafico_atual = None

url_icone_localizacao = "https://estudioweb.com.br/wp-content/uploads/2023/02/Emoji-Alvo-png.png"
INTERVALO_ATUALIZACAO_MINUTOS = 5

def atualizar_dados_estacao():
    dados_ecowitt = fetch_real_ecowitt_data() # Alterado para buscar dados reais
    now_app_tz = datetime.now(app_timezone)

    if dados_ecowitt is None:
        st.warning("Não foi possível buscar dados reais da estação. Verifique as mensagens de erro acima.")
        return False

    temp_ar_inferior = dados_ecowitt.get("temperature_c") # Do GW2000
    umid_rel = dados_ecowitt.get("humidity_percent")      # Do Wittboy (superior)
    temp_ar_superior = dados_ecowitt.get("temperature_superior_c") # Do Wittboy

    t_w, delta_t, condicao, desc_condicao, ponto_orvalho, sensacao_termica = \
        calcular_delta_t_e_condicao(temp_ar_superior, umid_rel)

    dados_completos = {
        "timestamp": now_app_tz.isoformat(),
        "temperature_c": temp_ar_inferior,
        "temperature_superior_c": temp_ar_superior,
        "humidity_percent": umid_rel,
        "wet_bulb_c": round(t_w, 2) if t_w is not None else None,
        "delta_t_c": round(delta_t, 2) if delta_t is not None else None,
        "condition_text": condicao if delta_t is not None else "ERRO CÁLCULO",
        "condition_description": desc_condicao,
        "dew_point_c": round(ponto_orvalho,1) if ponto_orvalho is not None else None,
        "feels_like_c": round(sensacao_termica,1) if sensacao_termica is not None else None,
        "wind_speed_kmh": dados_ecowitt.get("wind_speed_kmh"),
        "wind_gust_kmh": dados_ecowitt.get("wind_gust_kmh"),
        "wind_direction": dados_ecowitt.get("wind_direction"),
        "pressure_hpa": dados_ecowitt.get("pressure_hpa"),
        "uv_index": dados_ecowitt.get("uv_index"),
        "solar_radiation_wm2": dados_ecowitt.get("solar_radiation_wm2"),
        "luminosity_lux": dados_ecowitt.get("luminosity_lux"),
    }

    if delta_t is None and desc_condicao:
        st.error(f"Falha no cálculo Delta T: {desc_condicao}")

    salvar_dados_no_firestore_simulado(dados_completos)
    st.session_state.dados_atuais = dados_completos
    if imagem_base_pil:
        temp_plot = temp_ar_superior if delta_t is not None else temp_ar_inferior
        rh_plot = umid_rel
        if temp_plot is not None and rh_plot is not None: # Somente plota se tiver dados válidos
            st.session_state.imagem_grafico_atual = desenhar_grafico_com_ponto(
                imagem_base_pil, temp_plot, rh_plot, url_icone_localizacao
            )
        else: # Se não puder plotar, reseta para a imagem base ou nada
            st.session_state.imagem_grafico_atual = imagem_base_pil # Ou None, se preferir
            
    st.session_state.last_update_time = now_app_tz
    return delta_t is not None

# --- Interface Streamlit (com as alterações de layout solicitadas) ---

if st.session_state.last_update_time.year == 1970 or \
   st.session_state.last_update_time < (datetime.now(app_timezone) - timedelta(minutes=INTERVALO_ATUALIZACAO_MINUTOS)):
    atualizar_dados_estacao()

last_update_dt = st.session_state.last_update_time
last_update_str = last_update_dt.strftime('%d/%m/%Y %H:%M:%S') if last_update_dt.year > 1970 else 'Aguardando...'
st.caption(f"Última atualização: {last_update_str} (Horário Local: {APP_TIMEZONE_STR})")
st.markdown("---")

st.subheader("Condições Atuais da Estação")
dados = st.session_state.dados_atuais
if dados: 
    st.markdown("##### 🌡️ Temperatura e Umidade")
    col_t1, col_t2 = st.columns(2)
    
    with col_t1:
        # Temperatura do Wittboy (Superior) - agora é a principal e primeira
        if dados.get('temperature_superior_c') is not None:
            st.metric("Temperatura", 
                      f"{dados.get('temperature_superior_c'):.1f} °C", 
                      help="Temperatura do ar (sensor Wittboy - superior). Usada para cálculo do Delta T e derivados.")
        else:
            st.metric("Temperatura", "- °C", help="Temperatura do ar (sensor Wittboy - superior).")

        # Ponto de Orvalho (calculado com base na Temp. Superior e Umidade do Wittboy)
        st.metric("Ponto de Orvalho", 
                  f"{dados.get('dew_point_c', '-'):.1f} °C" if dados.get('dew_point_c') is not None else "- °C")

    with col_t2:
        # Umidade Relativa do Wittboy (usada para Delta T)
        st.metric("Umidade Relativa", 
                  f"{dados.get('humidity_percent', '-'):.1f} %" if dados.get('humidity_percent') is not None else "- %",
                  help="Umidade relativa (sensor Wittboy - superior).")
        
        # Sensação Térmica (calculada com base na Temp. Superior e Umidade do Wittboy)
        st.metric("Sensação Térmica", 
                  f"{dados.get('feels_like_c', '-'):.1f} °C" if dados.get('feels_like_c') is not None else "- °C")
    
    # A métrica "Temp. Ar (Inferior)" foi removida desta seção principal.
    # Ela ainda está disponível em `dados.get('temperature_c')` para o Indicador de Inversão Térmica.
    st.markdown("---")

    # Delta T (baseado na Temp Superior)
    dt_val = dados.get('delta_t_c')
    dt_cond = dados.get('condition_text', '-')
    dt_desc = dados.get('condition_description', 'Aguardando...')
    dt_color_map = {"INADEQUADA": "#FFA500", "ARRISCADA": "#FF0000", "ADEQUADA": "#00CC66", "ATENÇÃO": "#FFA500"}
    dt_bg = dt_color_map.get(dt_cond, "#F8D7DA" if "ERRO" in str(dt_cond).upper() else "lightgray")
    dt_txt = "#FFFFFF" if dt_cond in dt_color_map else ("#721C24" if "ERRO" in str(dt_cond).upper() else "black")

    st.markdown(f"<div style='text-align:center; margin-bottom:10px;'><span style='font-size:1.1em; font-weight:bold;'>Delta T (Base Temp. Sup.):</span><br><span style='font-size:2.2em; font-weight:bold; color:#007bff;'>{dt_val:.2f}°C</span></div>" if dt_val is not None else "<div style='text-align:center; margin-bottom:10px;'><span style='font-size:1.1em; font-weight:bold;'>Delta T:</span><br><span style='font-size:2.2em; font-weight:bold; color:gray;'>-</span></div>", unsafe_allow_html=True)
    st.markdown(f"<div style='background-color:{dt_bg}; color:{dt_txt}; padding:10px; border-radius:5px; text-align:center; margin-bottom:5px;'><strong style='font-size:1.1em;'>Condição Delta T: {dt_cond}</strong></div><p style='text-align:center; font-size:0.85em; color:#555;'>{dt_desc}</p>", unsafe_allow_html=True)
    st.markdown("---")

    # Vento e Pressão
    st.markdown("##### 💨 Vento e Pressão")
    col_v1, col_v2 = st.columns(2)
    vento_vel = dados.get('wind_speed_kmh', 0.0) if dados.get('wind_speed_kmh') is not None else 0.0
    cond_v_txt, desc_v_txt, bg_v_col, txt_v_col = "-", "", "lightgray", "black"
    if vento_vel <= 3: cond_v_txt, desc_v_txt, bg_v_col, txt_v_col = "INADEQUADO", "Risco inversão térmica.", "#FFA500", "#FFFFFF"
    elif 3 < vento_vel <= 12: cond_v_txt, desc_v_txt, bg_v_col, txt_v_col = "EXCELENTE", "Vento ideal.", "#00CC66", "#FFFFFF"
    else: cond_v_txt, desc_v_txt, bg_v_col, txt_v_col = "PERIGOSO", "Risco de deriva.", "#FF0000", "#FFFFFF"
    col_v1.metric("Vento Médio", f"{vento_vel:.1f} km/h")
    col_v1.metric("Pressão", f"{dados.get('pressure_hpa', '-'):.1f} hPa" if dados.get('pressure_hpa') is not None else "-")
    col_v2.metric("Rajadas", f"{dados.get('wind_gust_kmh', '-'):.1f} km/h" if dados.get('wind_gust_kmh') is not None else "-")
    col_v2.metric("Direção Vento", f"{dados.get('wind_direction', '-')}")
    st.markdown(f"<div style='background-color:{bg_v_col};color:{txt_v_col};padding:10px;border-radius:5px;text-align:center;margin-top:10px;margin-bottom:5px;'><strong style='font-size:1.1em'>Cond. Vento: {cond_v_txt}</strong></div><p style='text-align:center;font-size:0.85em;color:#555'>{desc_v_txt}</p>", unsafe_allow_html=True)
    st.markdown("---")

    # Indicador de Inversão Térmica com nomes completos
    st.markdown("##### 🌡️ Indicador de Inversão Térmica")
    t_inf, t_sup, v_inv = dados.get('temperature_c'), dados.get('temperature_superior_c'), dados.get('wind_speed_kmh')
    inv_cols = st.columns(3)
    inv_cols[0].metric("Temperatura Inferior", f"{t_inf:.1f}°C" if t_inf is not None else "N/D", help="Temperatura medida pelo GW2000 (base).")
    inv_cols[1].metric("Temperatura Superior", f"{t_sup:.1f}°C" if t_sup is not None else "N/D", help="Temperatura medida pelo Wittboy (topo).")
    inv_cols[2].metric("Vento Atual", f"{v_inv:.1f} km/h" if v_inv is not None else "N/D")

    s_inv, d_inv, bg_inv_col, txt_inv_col = "Aguardando...", "", "lightgray", "black"
    if all(val is not None for val in [t_inf, t_sup, v_inv]):
        if t_sup < t_inf: s_inv,d_inv,bg_inv_col,txt_inv_col = "APLICAÇÃO LIBERADA","Sem inversão.", "#00CC66","#FFFFFF"
        elif t_sup > t_inf:
            if v_inv < 3: s_inv,d_inv,bg_inv_col,txt_inv_col = "INVERSÃO TÉRMICA","Não aplicar!", "#FF0000","#FFFFFF"
            else: s_inv,d_inv,bg_inv_col,txt_inv_col = "CUIDADO!","Possível inversão.", "#FFA500","#FFFFFF"
        else: s_inv,d_inv = "CONDIÇÃO ESTÁVEL","Temps iguais."
    else: d_inv = "Dados insuficientes."
    st.markdown(f"<div style='background-color:{bg_inv_col};color:{txt_inv_col};padding:10px;border-radius:5px;text-align:center;margin-top:10px;margin-bottom:5px;'><strong style='font-size:1.1em'>{s_inv}</strong></div><p style='text-align:center;font-size:0.85em;color:#555'>{d_inv}</p>", unsafe_allow_html=True)
    st.markdown("---")
else:
    st.info("Aguardando dados da estação para exibir as condições atuais...")

if st.button("🔄 Forçar Atualização Manual", help="Busca novos dados da estação Ecowitt."):
    if atualizar_dados_estacao(): st.success("Dados atualizados!")
    else: st.error("Falha ao buscar ou processar dados da estação.")
    st.rerun()

st.subheader("Gráfico Delta T de Referência")
img_para_exibir = st.session_state.get('imagem_grafico_atual')
if img_para_exibir:
    ts_atual_str = datetime.fromisoformat(dados['timestamp']).astimezone(app_timezone).strftime('%d/%m/%Y %H:%M:%S') if dados and dados.get('timestamp') else "desconhecida"
    st.image(img_para_exibir, caption=f"Ponto plotado para dados de: {ts_atual_str}", use_container_width=True)
elif imagem_base_pil:
    st.image(imagem_base_pil, caption="Gráfico de referência (aguardando dados para ponto).", use_container_width=True)
else:
    st.warning("Imagem base do gráfico Delta T não pôde ser carregada.")
st.markdown("---")

st.subheader("Histórico de Dados da Estação")
historico_bruto = carregar_historico_do_firestore_simulado()
if historico_bruto:
    df_historico = pd.DataFrame(historico_bruto)
    if not df_historico.empty and 'timestamp' in df_historico.columns:
        try:
            df_historico['timestamp_dt'] = pd.to_datetime(df_historico['timestamp'].astype(str), errors='coerce')
            df_historico.dropna(subset=['timestamp_dt'], inplace=True)
            if df_historico['timestamp_dt'].dt.tz is None: # Verifica se é naive
                df_historico['timestamp_dt'] = df_historico['timestamp_dt'].dt.tz_localize('UTC').dt.tz_convert(app_timezone)
            else: # Se já for aware, apenas converte
                df_historico['timestamp_dt'] = df_historico['timestamp_dt'].dt.tz_convert(app_timezone)
            df_historico = df_historico.sort_values(by='timestamp_dt', ascending=False)

            st.markdown("##### Últimos Registros")
            cols_hist = ['timestamp_dt', 'temperature_c', 'temperature_superior_c', 'humidity_percent', 'delta_t_c', 'condition_text', 'wind_speed_kmh']
            df_display = df_historico[[col for col in cols_hist if col in df_historico.columns]].head(10).copy()
            mapa_nomes = {'timestamp_dt': "Data/Hora",'temperature_c': "T.Inf(°C)",'temperature_superior_c': "T.Sup(°C)", 'humidity_percent': "UR(%)",'delta_t_c': "ΔT(°C)",'condition_text': "Cond.ΔT",'wind_speed_kmh': "Vento(km/h)"}
            df_display.rename(columns=mapa_nomes, inplace=True)
            if "Data/Hora" in df_display.columns:
                df_display.loc[:, "Data/Hora"] = df_display["Data/Hora"].dt.strftime('%d/%m/%y %H:%M')
            st.dataframe(df_display, use_container_width=True, hide_index=True)
            st.markdown("---")

            st.subheader("Tendências Recentes")
            df_chart_full = df_historico.set_index('timestamp_dt').sort_index()
            opts_int = {"1 H":1,"3 H":3,"12 H":12,"24 H":24,"3 D":72,"7 D":168,"Tudo":None}
            
            sel_int_label = st.radio("Intervalo Gráficos:", list(opts_int.keys())+["Custom"], horizontal=True, key="sel_int_graf")
            
            df_chart_filt = pd.DataFrame(); now_filt = datetime.now(app_timezone)

            if sel_int_label == "Custom":
                date_picker_cols = st.columns(2) 
                if len(date_picker_cols) == 2:
                    c_start, c_end = date_picker_cols
                    min_hist_dt_val = (now_filt - timedelta(days=7)).date()
                    if not df_chart_full.empty and pd.notna(df_chart_full.index.min()):
                         min_hist_dt_val = df_chart_full.index.min().date()
                    
                    start_val = st.session_state.get('d_start_pick_val', min_hist_dt_val)
                    end_val = st.session_state.get('d_end_pick_val', now_filt.date())

                    d_start = c_start.date_input("Início", value=start_val, min_value=(now_filt - timedelta(days=730)).date(), max_value=now_filt.date(), key="d_start_pick_ui")
                    if d_start: st.session_state.d_start_pick_val = d_start
                    
                    if d_start and end_val < d_start: end_val = d_start
                    
                    d_end = c_end.date_input("Fim", value=end_val, min_value=d_start if d_start else (now_filt - timedelta(days=730)).date(), max_value=now_filt.date(), key="d_end_pick_ui")
                    if d_end: st.session_state.d_end_pick_val = d_end

                    if d_start and d_end:
                        s_dt = app_timezone.localize(datetime.combine(d_start, time.min)); e_dt = app_timezone.localize(datetime.combine(d_end, time.max))
                        df_chart_filt = df_chart_full[(df_chart_full.index >= s_dt) & (df_chart_full.index <= e_dt)]
                    else: df_chart_filt = pd.DataFrame()
                else:
                    st.error("Falha interna: colunas para datas."); df_chart_filt = pd.DataFrame()
            else:
                horas = opts_int.get(sel_int_label)
                if horas is not None: df_chart_filt = df_chart_full[df_chart_full.index >= (now_filt - timedelta(hours=horas))]
                else: df_chart_filt = df_chart_full
            
            if not df_chart_filt.empty:
                df_alt = df_chart_filt.reset_index()
                common_x = alt.X('timestamp_dt:T', title='Data/Hora', axis=alt.Axis(format='%d/%m %Hh'))
                tooltip_ts = alt.Tooltip('timestamp_dt:T', title='Data/Hora', format='%d/%m %H:%M')

                delta_t_c_chart = alt.Chart(df_alt.dropna(subset=['delta_t_c'])).mark_line(point=alt.OverlayMarkDef(size=20), interpolate='monotone').encode(
                    x=common_x, y=alt.Y('delta_t_c:Q', title='ΔT (°C)'),
                    color=alt.condition(alt.LogicalOrPredicate(predicates=[alt.LogicalAndPredicate(predicates=[alt.datum.delta_t_c>=0,alt.datum.delta_t_c<2]), alt.LogicalAndPredicate(predicates=[alt.datum.delta_t_c>8,alt.datum.delta_t_c<=10])]), alt.value('orange'),
                                      alt.condition(alt.LogicalAndPredicate(predicates=[alt.datum.delta_t_c>=2,alt.datum.delta_t_c<=8]), alt.value('#00CC66'),
                                                    alt.condition(alt.datum.delta_t_c>10,alt.value('red'),alt.value('lightgray')))),
                    tooltip=[tooltip_ts, alt.Tooltip('delta_t_c:Q',title='ΔT(°C)',format='.2f'), alt.Tooltip('condition_text:N',title='Cond.ΔT')]
                ).properties(title='Tendência Delta T (base T.Superior)').interactive()
                st.altair_chart(delta_t_c_chart, use_container_width=True)

                for col, title_chart, color_c in [('temperature_c','T.Inf.(°C)','royalblue'),('temperature_superior_c','T.Sup.(°C)','orangered'), ('humidity_percent','UR(%)','forestgreen'),('wind_speed_kmh','Vento(km/h)','slategray')]:
                    if col in df_alt.columns:
                        chart = alt.Chart(df_alt.dropna(subset=[col])).mark_line(point=True, color=color_c).encode(
                            x=common_x, y=alt.Y(f'{col}:Q', title=title_chart), tooltip=[tooltip_ts, alt.Tooltip(f'{col}:Q', title=title_chart, format='.1f')]
                        ).properties(title=f'Tendência {title_chart}').interactive()
                        st.altair_chart(chart, use_container_width=True)
            else: st.info("Sem dados históricos para o intervalo selecionado.")
        except Exception as e_pd:
            st.error(f"Erro ao formatar histórico ou gerar gráficos: {e_pd}")
            import traceback
            print(f"Pandas/Altair Error: {e_pd}\n{traceback.format_exc()}")
else: st.info("Nenhum histórico de dados encontrado.")

st.markdown("---")
st.markdown("""
**Notas:**
- **Delta T:** Calculado com a **Temperatura e Umidade do Sensor Superior** (WS90).
- **Temperatura Inferior:** Medida pelo Gateway **GW2000**.
- **Inversão Térmica:** Avaliada comparando T. Inferior, T. Superior e Vento.

""")

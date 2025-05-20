import streamlit as st
import math
import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
from datetime import datetime, timedelta
import time
import random # Para simular dados da Ecowitt

# --- Simulação do Firestore (substitua pela integração real) ---
if 'db_historico' not in st.session_state:
    st.session_state.db_historico = []

def salvar_dados_no_firestore_simulado(dados):
    # print(f"Simulando salvamento no Firestore: {dados}")
    st.session_state.db_historico.append(dados)
    max_historico = 100
    if len(st.session_state.db_historico) > max_historico:
        st.session_state.db_historico = st.session_state.db_historico[-max_historico:]

def carregar_historico_do_firestore_simulado():
    # print("Simulando carregamento do Firestore.")
    return sorted(st.session_state.db_historico, key=lambda x: x['timestamp'], reverse=True)

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
    if not (0 <= rh <= 100):
        return None, None, "Erro: Umidade Relativa fora da faixa (0-100%).", None, None, None, None
    if not (0 <= t_bs <= 50): 
        return None, None, f"Erro: Temperatura do Ar ({t_bs}°C) fora da faixa de cálculo (0-50°C).", None, None, None, None
    try:
        t_w = calcular_temperatura_bulbo_umido_stull(t_bs, rh)
        delta_t = t_bs - t_w
        
        ponto_orvalho = t_bs - ((100 - rh) / 5.0)
        sensacao_termica = t_bs + 0.3 * (rh/100 * 6.105 * math.exp(17.27 * t_bs / (237.7 + t_bs)) - 10)
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
        else:
            condicao_texto = "ATENÇÃO"
            descricao_condicao = f"Condição limite (Delta T {delta_t:.1f}°C)."
        
        return t_w, delta_t, condicao_texto, descricao_condicao, ponto_orvalho, sensacao_termica
    except Exception as e:
        return None, None, f"Erro no cálculo: {e}", None, None, None, None


# --- FUNÇÃO PARA DESENHAR PONTO E ÍCONE NO GRÁFICO ---
def desenhar_grafico_com_ponto(imagem_base_pil, temp_usuario, rh_usuario, url_icone):
    if imagem_base_pil is None: return None
    
    img_processada = imagem_base_pil.copy()
    draw = ImageDraw.Draw(img_processada)

    temp_min_grafico = 0.0
    temp_max_grafico = 50.0
    pixel_x_min_temp = 196
    pixel_x_max_temp = 906

    rh_min_grafico = 10.0
    rh_max_grafico = 100.0
    pixel_y_min_rh = 921
    pixel_y_max_rh = 356

    if temp_usuario is not None and rh_usuario is not None:
        plotar_temp = max(temp_min_grafico, min(temp_usuario, temp_max_grafico))
        plotar_rh = max(rh_min_grafico, min(rh_usuario, rh_max_grafico))

        range_temp_grafico = temp_max_grafico - temp_min_grafico
        percent_temp = (plotar_temp - temp_min_grafico) / range_temp_grafico if range_temp_grafico != 0 else 0
        pixel_x_usuario = int(pixel_x_min_temp + percent_temp * (pixel_x_max_temp - pixel_x_min_temp))

        range_rh_grafico = rh_max_grafico - rh_min_grafico
        percent_rh = (plotar_rh - rh_min_grafico) / range_rh_grafico if range_rh_grafico != 0 else 0
        pixel_y_usuario = int(pixel_y_min_rh - percent_rh * (pixel_y_min_rh - pixel_y_max_rh))

        # Desenhar o ponto preto
        raio_ponto = 10  # Raio do ponto preto
        cor_ponto = "black"
        draw.ellipse([(pixel_x_usuario - raio_ponto, pixel_y_usuario - raio_ponto),
                      (pixel_x_usuario + raio_ponto, pixel_y_usuario + raio_ponto)],
                     fill=cor_ponto, outline=cor_ponto) # Ponto preto sem contorno de outra cor
        
        try:
            response_icone = requests.get(url_icone, timeout=10)
            response_icone.raise_for_status()
            icone_img_original = Image.open(BytesIO(response_icone.content)).convert("RGBA")
            
            # O tamanho do ícone pode ser um pouco menor que o ponto para que o ponto seja visível por baixo
            # ou do mesmo tamanho se a imagem do ícone tiver transparência adequada.
            tamanho_icone = (35, 35) # Ajuste conforme necessário
            icone_redimensionado = icone_img_original.resize(tamanho_icone, Image.Resampling.LANCZOS)
            
            # Centraliza o ícone sobre o ponto preto
            pos_x_icone = pixel_x_usuario - tamanho_icone[0] // 2
            pos_y_icone = pixel_y_usuario - tamanho_icone[1] // 2 
            
            # Colar o ícone usando sua máscara alfa para transparência
            img_processada.paste(icone_redimensionado, (pos_x_icone, pos_y_icone), icone_redimensionado)
        except Exception as e_icon:
            print(f"Erro ao processar ícone: {e_icon}")
            st.warning(f"Não foi possível carregar o ícone de marcação: {e_icon}")
            
    return img_processada

# --- LÓGICA DA APLICAÇÃO STREAMLIT ---
st.set_page_config(page_title="Estação Meteorológica - BASE AGRO", layout="wide")
st.title("🌦️ Estação Meteorológica - BASE AGRO")

if 'last_update_time' not in st.session_state: st.session_state.last_update_time = datetime.min
if 'dados_atuais' not in st.session_state: st.session_state.dados_atuais = None
if 'imagem_grafico_atual' not in st.session_state: st.session_state.imagem_grafico_atual = None

url_grafico_base = "https://d335luupugsy2.cloudfront.net/images%2Flanding_page%2F2083383%2F16.png"
# --- URL DO NOVO ÍCONE ATUALIZADA ---
url_icone_localizacao = "https://clipground.com/images/address-clipart-logo-9.png"
INTERVALO_ATUALIZACAO_MINUTOS = 5

@st.cache_data(ttl=3600)
def carregar_imagem_base(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGBA")
    except requests.exceptions.RequestException as e:
        st.error(f"Erro ao baixar a imagem base do gráfico: {e}")
        return None

imagem_base_pil = carregar_imagem_base(url_grafico_base)

def buscar_dados_ecowitt_simulado():
    time.sleep(0.5)
    temp = round(random.uniform(0, 50), 1)    
    umid = round(random.uniform(10, 100), 1) 
    vento_vel = round(random.uniform(0, 20), 1)
    vento_raj = round(vento_vel + random.uniform(0, 15), 1)
    pressao = round(random.uniform(1000, 1025), 1)
    direcoes_vento = ["N", "NE", "L", "SE", "S", "SO", "O", "NO"]
    vento_dir = random.choice(direcoes_vento)
    altitude = 314
    uv_index = random.randint(0, 11)
    luminosidade = random.randint(1000, 80000)
    radiacao_solar = random.randint(50, 900)
    return {
        "temperature_c": temp, "humidity_percent": umid,
        "wind_speed_kmh": vento_vel, "wind_gust_kmh": vento_raj,
        "pressure_hpa": pressao, "wind_direction": vento_dir, "altitude_m": altitude,
        "uv_index": uv_index, "luminosity_lux": luminosidade, "solar_radiation_wm2": radiacao_solar
    }

def atualizar_dados_estacao():
    dados_ecowitt = buscar_dados_ecowitt_simulado()
    if dados_ecowitt:
        temp_ar = dados_ecowitt["temperature_c"]
        umid_rel = dados_ecowitt["humidity_percent"]
        t_w, delta_t, condicao, desc_condicao, ponto_orvalho, sensacao_termica = calcular_delta_t_e_condicao(temp_ar, umid_rel)
        if t_w is not None and delta_t is not None:
            dados_para_salvar = {
                "timestamp": datetime.now().isoformat(), "temperature_c": temp_ar,
                "humidity_percent": umid_rel, "wet_bulb_c": round(t_w, 2),
                "delta_t_c": round(delta_t, 2), "condition_text": condicao,
                "condition_description": desc_condicao,
                "dew_point_c": round(ponto_orvalho,1) if ponto_orvalho is not None else None,
                "feels_like_c": round(sensacao_termica,1) if sensacao_termica is not None else None,
                **dados_ecowitt
            }
            salvar_dados_no_firestore_simulado(dados_para_salvar)
            st.session_state.dados_atuais = dados_para_salvar
            if imagem_base_pil:
                st.session_state.imagem_grafico_atual = desenhar_grafico_com_ponto(
                    imagem_base_pil, 
                    temp_ar, umid_rel, url_icone_localizacao
                )
            st.session_state.last_update_time = datetime.now()
            return True
        else:
            st.error(f"Erro no cálculo Delta T: {condicao}")
            dados_erro = {
                "timestamp": datetime.now().isoformat(), "temperature_c": temp_ar,
                "humidity_percent": umid_rel, "wet_bulb_c": None, "delta_t_c": None,
                "condition_text": "ERRO CÁLCULO", "condition_description": condicao, **dados_ecowitt
            }
            st.session_state.dados_atuais = dados_erro
            if imagem_base_pil:
                 st.session_state.imagem_grafico_atual = desenhar_grafico_com_ponto(
                    imagem_base_pil, temp_ar, umid_rel, url_icone_localizacao
                )
            st.session_state.last_update_time = datetime.now()
            return False
    else:
        st.error("Não foi possível obter os dados da estação Ecowitt (simulado).")
    return False

agora_atual = datetime.now()
if st.session_state.last_update_time == datetime.min or \
   st.session_state.last_update_time < (agora_atual - timedelta(minutes=INTERVALO_ATUALIZACAO_MINUTOS)):
    if st.session_state.last_update_time == datetime.min and 'simulacao_info_mostrada' not in st.session_state:
        st.info("Usando dados simulados. Substitua `buscar_dados_ecowitt_simulado` pela sua integração real com a API Ecowitt.")
        st.session_state.simulacao_info_mostrada = True
    if atualizar_dados_estacao():
        if 'running_first_time' not in st.session_state: st.rerun()
        st.session_state.running_first_time = False

st.caption(f"Última atualização dos dados: {st.session_state.last_update_time.strftime('%d/%m/%Y %H:%M:%S') if st.session_state.last_update_time > datetime.min else 'Aguardando primeira atualização...'}")
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
        if condicao_atual_texto == "INADEQUADA": cor_fundo_condicao = "#FFD2D2"; cor_texto_condicao = "#D8000C"
        elif condicao_atual_texto == "ARRISCADA": cor_fundo_condicao = "#FFF3CD"; cor_texto_condicao = "#B08D00"
        elif condicao_atual_texto == "ADEQUADA": cor_fundo_condicao = "#D4EDDA"; cor_texto_condicao = "#155724"
        elif condicao_atual_texto == "ATENÇÃO": cor_fundo_condicao = "#FFE9C5"; cor_texto_condicao = "#A76800"
        elif condicao_atual_texto == "ERRO CÁLCULO": cor_fundo_condicao = "#F8D7DA"; cor_texto_condicao = "#721C24"
        
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

        if vento_velocidade_atual <= 3:
            condicao_vento_texto = "ARRISCADO"
            desc_condicao_vento = "Risco de inversão térmica."
            cor_fundo_vento = "#FFE9C5"; cor_texto_vento = "#A76800"
        elif 3 < vento_velocidade_atual <= 10:
            condicao_vento_texto = "EXCELENTE"
            desc_condicao_vento = "Condições ideais de vento."
            cor_fundo_vento = "#D4EDDA"; cor_texto_vento = "#155724"
        else: 
            condicao_vento_texto = "MUITO PERIGOSO"
            desc_condicao_vento = "Risco de deriva."
            cor_fundo_vento = "#FFD2D2"; cor_texto_condicao = "#D8000C"
            
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
    st.subheader("Gráfico Delta T")
    imagem_para_exibir = st.session_state.get('imagem_grafico_atual') or imagem_base_pil
                         
    if imagem_para_exibir:
        caption_text = "Gráfico de referência Delta T"
        if st.session_state.get('dados_atuais') and 'timestamp' in st.session_state.dados_atuais:
            try:
                ts_obj = datetime.fromisoformat(st.session_state.dados_atuais['timestamp'])
                caption_text = f"Ponto indicativo para dados de: {ts_obj.strftime('%d/%m/%Y %H:%M:%S')}"
            except: caption_text = f"Ponto indicativo para dados de: {st.session_state.dados_atuais['timestamp']}"
        st.image(imagem_para_exibir, caption=caption_text, use_container_width=True)
    else:
        st.warning("Imagem base do gráfico não disponível.")

st.markdown("---")
st.subheader("Histórico de Dados da Estação (Últimos Registros)")
historico = carregar_historico_do_firestore_simulado()
if historico:
    import pandas as pd
    df_historico = pd.DataFrame(historico)
    if not df_historico.empty and 'timestamp' in df_historico.columns:
        try:
            df_historico['timestamp_dt'] = pd.to_datetime(df_historico['timestamp'])
            df_historico = df_historico.sort_values(by='timestamp_dt', ascending=False)
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
                 df_display["Data/Hora"] = df_display["Data/Hora"].dt.strftime('%d/%m/%Y %H:%M:%S')
            st.dataframe(df_display, use_container_width=True, hide_index=True)
        except Exception as e_pd:
            print(f"Erro ao processar DataFrame do histórico: {e_pd}")
            st.error("Erro ao formatar histórico para exibição.")
    if not df_historico.empty and 'timestamp_dt' in df_historico.columns and len(df_historico) > 1 :
        st.subheader("Tendências Recentes")
        try:
            df_chart = df_historico.set_index('timestamp_dt').sort_index()
            colunas_numericas_chart = ['temperature_c', 'humidity_percent', 'delta_t_c', 'wind_speed_kmh']
            colunas_presentes_chart = [col for col in colunas_numericas_chart if col in df_chart.columns]
            if colunas_presentes_chart:
                 st.line_chart(df_chart[colunas_presentes_chart])
            else: st.warning("Sem dados suficientes para gráfico de tendências.")
        except Exception as e_chart:
            print(f"Erro ao gerar gráfico de linha do histórico: {e_chart}")
            st.warning("Não foi possível gerar o gráfico de tendências.")
else:
    st.info("Nenhum histórico de dados encontrado.")

st.markdown("---")
st.markdown("""
**Notas:**
- Este aplicativo tenta buscar dados (simulados) de uma estação Ecowitt a cada 5 minutos.
- **Para uso real, substitua a função `buscar_dados_ecowitt_simulado()` pela sua integração com a API da sua estação Ecowitt.**
- O histórico é armazenado (simulado) e exibido. Para persistência real, integre com um banco de dados.
- As coordenadas de pixel para o gráfico são baseadas nas suas especificações.
""")

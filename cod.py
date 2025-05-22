import streamlit as st
import math
import requests
from PIL import Image, ImageDraw
from io import BytesIO

# --- SUAS FUNÇÕES DE CÁLCULO (sem alteração) ---
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

def calcular_delta_t(t_bs, rh):
    if not (0 <= rh <= 100):
        return "Erro: A umidade relativa deve estar entre 0 e 100%.", None
    # Ajustando a faixa de temperatura de bulbo seco conforme o gráfico e inputs anteriores
    if not (0 <= t_bs <= 50): # Faixa dos inputs e do gráfico
        return f"Erro: Temperatura de bulbo seco ({t_bs}°C) fora da faixa esperada (0 a 50°C).", None
    try:
        t_w = calcular_temperatura_bulbo_umido_stull(t_bs, rh)
        delta_t = t_bs - t_w
        return delta_t, t_w
    except Exception as e:
        return f"Erro no cálculo: {e}", None

# --- FUNÇÃO PARA DESENHAR AS LINHAS NA IMAGEM (ajustes nos limites se necessário) ---
def desenhar_linhas_no_grafico(imagem_base_pil, temp_usuario, rh_usuario):
    img_com_linhas = imagem_base_pil.copy()
    draw = ImageDraw.Draw(img_com_linhas)

    # Coordenadas e escalas do gráfico (ajuste fino pode ser necessário)
    temp_min_grafico = 5.0
    temp_max_grafico = 45.0 # O gráfico parece ir até 45C
    pixel_x_min_temp = 115  # Pixel X para temp_min_grafico (estimativa)
    pixel_x_max_temp = 960  # Pixel X para temp_max_grafico (estimativa)

    rh_min_grafico = 10.0
    rh_max_grafico = 90.0 # O gráfico mostra linhas de RH até 90%
    pixel_y_min_rh = 890  # Pixel Y para rh_min_grafico (base do gráfico)
    pixel_y_max_rh = 100  # Pixel Y para rh_max_grafico (topo das linhas de RH)

    # Verificar se os valores estão dentro da faixa plotável do gráfico
    # É importante que temp_usuario e rh_usuario estejam dentro dos limites visuais do gráfico
    # para que as linhas apareçam corretamente.
    plotar_temp = max(temp_min_grafico, min(temp_usuario, temp_max_grafico))
    plotar_rh = max(rh_min_grafico, min(rh_usuario, rh_max_grafico))

    percent_temp = (plotar_temp - temp_min_grafico) / (temp_max_grafico - temp_min_grafico)
    pixel_x_usuario = pixel_x_min_temp + percent_temp * (pixel_x_max_temp - pixel_x_min_temp)

    percent_rh = (plotar_rh - rh_min_grafico) / (rh_max_grafico - rh_min_grafico)
    pixel_y_usuario = pixel_y_min_rh - percent_rh * (pixel_y_min_rh - pixel_y_max_rh)

    # Desenhar linhas
    draw.line([(pixel_x_usuario, pixel_y_min_rh), (pixel_x_usuario, pixel_y_max_rh)], fill="blue", width=4)
    draw.line([(pixel_x_min_temp, pixel_y_usuario), (pixel_x_max_temp, pixel_y_usuario)], fill="blue", width=4)

    raio_circulo = 8
    draw.ellipse([(pixel_x_usuario - raio_circulo, pixel_y_usuario - raio_circulo),
                  (pixel_x_usuario + raio_circulo, pixel_y_usuario + raio_circulo)],
                 fill="red", outline="black", width=2)
    return img_com_linhas

# --- Interface Streamlit ---
st.set_page_config(page_title="Análise Delta T para Pulverização", layout="wide")
st.title("💧 Análise Delta T e Condições para Pulverização")
st.caption(f"Última atualização dos dados da calculadora: {math.pi:.2f} (exemplo, poderia ser uma data/hora real)") # Exemplo de timestamp

url_grafico_base = "https://d335luupugsy2.cloudfront.net/images%2Flanding_page%2F2083383%2F16.png"
imagem_base_pil = None
try:
    response = requests.get(url_grafico_base)
    response.raise_for_status()
    imagem_base_pil = Image.open(BytesIO(response.content)).convert("RGBA")
except requests.exceptions.RequestException as e:
    st.error(f"Erro ao baixar a imagem base do gráfico: {e}")

# Layout em três colunas para simular blocos de informação
col_entrada, col_analise, col_grafico_dinamico = st.columns([1, 1, 1.5]) # Ajuste as proporções

with col_entrada:
    st.subheader("Parâmetros Atuais")
    temp_bulbo_seco_input = st.number_input(
        "Temperatura de Bulbo Seco (°C):",
        min_value=0.0, max_value=50.0, value=25.0, step=0.1, format="%.1f",
        help="Temperatura atual do ar medida por um termômetro de bulbo seco."
    )
    umidade_relativa_input = st.number_input(
        "Umidade Relativa (%):",
        min_value=0.0, max_value=100.0, value=60.0, step=0.1, format="%.1f",
        help="Percentual de umidade no ar em relação ao máximo que poderia conter naquela temperatura."
    )
    calcular_btn = st.button("Analisar Condições", type="primary", use_container_width=True)

with col_analise:
    st.subheader("Resultados e Condição")
    if calcular_btn:
        # Validação dos inputs antes de passar para o cálculo
        if not (0 <= temp_bulbo_seco_input <= 50):
             st.error("Temperatura de Bulbo Seco fora da faixa aceitável (0-50°C).")
        elif not (0 <= umidade_relativa_input <= 100):
             st.error("Umidade Relativa fora da faixa aceitável (0-100%).")
        else:
            resultado_delta_t, t_w_calculada = calcular_delta_t(temp_bulbo_seco_input, umidade_relativa_input)
            if isinstance(resultado_delta_t, str): # Se for mensagem de erro
                st.error(resultado_delta_t)
                st.metric(label="Temperatura Bulbo Úmido", value="- °C")
                st.metric(label="Delta T", value="- °C")
                st.markdown("**Condição para Pulverização:** -")
            elif t_w_calculada is not None:
                st.metric(label="Temp. Bulbo Úmido (Tw)", value=f"{t_w_calculada:.2f} °C")
                st.metric(label="Delta T (Tbs - Tw)", value=f"{resultado_delta_t:.2f} °C", delta_color="off")

                condicao_texto = ""
                cor_condicao = "gray"
                if resultado_delta_t < 2:
                    condicao_texto = "🔴 INADEQUADA (Delta T < 2): Alto risco de deriva/escorrimento."
                    cor_condicao = "red"
                elif resultado_delta_t > 10: # O site de referência pode usar limites diferentes (ex: >8 ou >12)
                    condicao_texto = "🟠 ARRISCADA (Delta T > 10): Risco de evaporação excessiva."
                    cor_condicao = "orange"
                elif 2 <= resultado_delta_t <= 8: # Faixa ideal comum
                    condicao_texto = "🟢 ADEQUADA (Delta T 2-8): Condições ideais."
                    cor_condicao = "green"
                else: # Entre 8 e 10 (ou o limite superior que você definir)
                    condicao_texto = f"🟡 ATENÇÃO (Delta T {resultado_delta_t:.1f}): Condição limite."
                    cor_condicao = "yellow"

                st.markdown(f"**Condição para Pulverização:** <span style='color:{cor_condicao}; font-weight:bold;'>{condicao_texto}</span>", unsafe_allow_html=True)
            else:
                st.error("Ocorreu um erro desconhecido no cálculo.")
    else:
        st.info("Insira os dados e clique em 'Analisar Condições'.")
        st.metric(label="Temp. Bulbo Úmido (Tw)", value="- °C")
        st.metric(label="Delta T (Tbs - Tw)", value="- °C")
        st.markdown("**Condição para Pulverização:** -")

with col_grafico_dinamico:
    st.subheader("Visualização no Gráfico Delta T")
    if imagem_base_pil:
        if calcular_btn and 'resultado_delta_t' in locals() and not isinstance(resultado_delta_t, str):
             # Apenas desenha se o cálculo foi bem sucedido
            img_com_linhas = desenhar_linhas_no_grafico(imagem_base_pil, temp_bulbo_seco_input, umidade_relativa_input)
            st.image(img_com_linhas, caption=f"Ponto atual: {temp_bulbo_seco_input}°C, {umidade_relativa_input}% RH", use_column_width=True)
        else:
            # Mostra o gráfico base se não clicou ou se houve erro no cálculo
            st.image(imagem_base_pil, caption="Gráfico de referência Delta T", use_column_width=True)
    else:
        st.warning("Imagem base do gráfico não disponível.")

st.markdown("---")
st.markdown("""
**Sobre os Cálculos:**
- **Temperatura de Bulbo Úmido ($T_w$)**: Estimada pela fórmula de Stull. É a menor temperatura para a qual o ar pode ser resfriado por evaporação de água, a pressão constante.
- **Delta T ($\Delta T$)**: Diferença entre a Temperatura de Bulbo Seco ($T_{bs}$) e a Temperatura de Bulbo Úmido ($T_w$). É um indicador crucial das condições de evaporação para pulverização agrícola.
""")
st.latex(r''' \Delta T = T_{bs} - T_w ''')

import streamlit as st
import math

# Suas funções de cálculo (exatamente como antes)
def calcular_temperatura_bulbo_umido_stull(t_bs, rh):
    """
    Calcula a temperatura de bulbo úmido (Tw) usando a fórmula de Stull.
    :param t_bs: Temperatura de bulbo seco em Celsius.
    :param rh: Umidade relativa em porcentagem (ex: 60 para 60%).
    :return: Temperatura de bulbo úmido em Celsius.
    """
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
    """
    Calcula o Delta T a partir da temperatura de bulbo seco e umidade relativa.
    :param t_bs: Temperatura de bulbo seco em Celsius.
    :param rh: Umidade relativa em porcentagem (ex: 60 para 60%).
    :return: Tupla (Valor do Delta T em Celsius, Temperatura de Bulbo Úmido em Celsius)
             ou (mensagem de erro, None) se a entrada for inválida.
    """
    if not (0 <= rh <= 100):
        return "Erro: A umidade relativa deve estar entre 0 e 100%.", None
    if t_bs < -50 or t_bs > 60: # Exemplo de validação para temperatura
        return "Erro: Temperatura de bulbo seco fora da faixa esperada (-50 a 60°C).", None
    try:
        t_w = calcular_temperatura_bulbo_umido_stull(t_bs, rh)
        delta_t = t_bs - t_w
        return delta_t, t_w
    except Exception as e:
        return f"Erro no cálculo: {e}", None

# --- Interface Streamlit ---
st.set_page_config(page_title="Calculadora Delta T", layout="wide")

st.title("💧 Calculadora de Delta T para Pulverização")
st.caption("Baseada na fórmula de Stull para Temperatura de Bulbo Úmido.")

# ADICIONANDO A IMAGEM AQUI:
url_da_imagem = "https://i.postimg.cc/zXZpjrnd/Screenshot-20250520-192948-Drive.jpg"
st.image(url_da_imagem, caption="Interpretação do Delta T para Pulverização Agrícola", use_column_width=True) # Adicione um caption se desejar e ajuste o tamanho

# Layout com colunas para entrada e resultados
col_entrada, col_resultados = st.columns(2)

with col_entrada:
    st.header("Entrada de Dados")
    temp_bulbo_seco_input = st.number_input(
        "Temperatura de Bulbo Seco (°C):",
        min_value=-50.0,
        max_value=60.0,
        value=25.0,
        step=0.1,
        format="%.1f"
    )
    umidade_relativa_input = st.number_input(
        "Umidade Relativa (%):",
        min_value=0.0,
        max_value=100.0,
        value=60.0,
        step=0.1,
        format="%.1f"
    )
    calcular_btn = st.button("Calcular Delta T", type="primary")

with col_resultados:
    st.header("Resultados")
    if calcular_btn:
        resultado_delta_t, t_w_calculada = calcular_delta_t(temp_bulbo_seco_input, umidade_relativa_input)

        if isinstance(resultado_delta_t, str): # Verifica se retornou uma mensagem de erro
            st.error(resultado_delta_t)
            st.metric(label="Temperatura Bulbo Úmido", value="- °C")
            st.metric(label="Delta T", value="- °C")
            st.info("Condição: -")
        elif t_w_calculada is not None:
            st.metric(label="Temperatura Bulbo Úmido", value=f"{t_w_calculada:.2f} °C")
            st.metric(label="Delta T", value=f"{resultado_delta_t:.2f} °C", delta_color="off") # Delta color 'off' para não interpretar valor como positivo/negativo

            st.subheader("Interpretação do Delta T:")
            if resultado_delta_t < 2:
                st.warning("🔴 Condição: Delta T baixo (< 2°C). Risco de escorrimento/deriva por inversão.")
            elif resultado_delta_t > 10: # Limite superior pode variar (ex: 8 ou 12)
                st.warning(f"🟠 Condição: Delta T alto (> 10°C). Risco de evaporação excessiva das gotas.")
            elif 2 <= resultado_delta_t <= 8: # Faixa ideal comum
                st.success("🟢 Condição: Delta T ideal (2-8°C) para pulverização.")
            else: # Entre 8 e 10 (ou o limite superior escolhido)
                st.info(f"🟡 Condição: Delta T em atenção/limite ({resultado_delta_t:.1f}°C).")
        else:
            st.error("Ocorreu um erro desconhecido no cálculo.")
    else:
        st.info("Ajuste os valores à esquerda e clique em 'Calcular Delta T'.")
        st.metric(label="Temperatura Bulbo Úmido", value="- °C")
        st.metric(label="Delta T", value="- °C")
        st.info("Condição: -")


st.markdown("---")
st.markdown("A **Temperatura de Bulbo Úmido ($T_w$)** é a menor temperatura para a qual o ar pode ser resfriado por evaporação de água nele, a pressão constante. A fórmula de Stull é uma aproximação empírica.")
st.markdown("O **Delta T ($\Delta T$)** é a diferença entre a Temperatura de Bulbo Seco ($T_{bs}$) e a Temperatura de Bulbo Úmido ($T_w$). É um indicador das condições de evaporação e da adequação para pulverização agrícola.")
st.latex(r''' \Delta T = T_{bs} - T_w ''')

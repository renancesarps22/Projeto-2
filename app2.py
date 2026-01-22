import io
import os
from datetime import date, timedelta
import pandas as pd
import streamlit as st
import plotly.express as px
import httpx
from sqlalchemy import create_engine, text

# --- CONFIGURAÇÃO DA PÁGINA (Mobile Friendly) ---
st.set_page_config(
    page_title="App Personal", 
    layout="wide", 
    initial_sidebar_state="collapsed" # Esconde sidebar no mobile
)

# --- SEGREDOS E CONEXÃO ---
# Certifique-se de configurar .streamlit/secrets.toml com:
# [supabase]
# url = "..."
# anon_key = "..."
# db_url = "..."

try:
    SUPABASE_URL = st.secrets["supabase"]["url"]
    SUPABASE_KEY = st.secrets["supabase"]["anon_key"]
    DATABASE_URL = st.secrets["supabase"]["db_url"]
except KeyError:
    st.error("Configuração de secrets incompleta. Verifique o arquivo .streamlit/secrets.toml")
    st.stop()

# Cache da conexão SQL
@st.cache_resource
def get_engine():
    return create_engine(DATABASE_URL)

# --- FUNÇÕES DE AUTH (Via API REST do Supabase) ---
def sb_login(email, password):
    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    headers = {"apikey": SUPABASE_KEY, "Content-Type": "application/json"}
    try:
        resp = httpx.post(url, headers=headers, json={"email": email, "password": password}, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPStatusError as e:
        # Tenta ler a mensagem de erro detalhada do Supabase
        try:
            err_json = e.response.json()
            msg = err_json.get("error_description") or err_json.get("msg") or e.response.text
            st.error(f"Erro de Login: {msg}")
        except:
            st.error(f"Erro HTTP: {e}")
        return None
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return None

def get_user_profile(user_id, token):
    # Busca role e nome na tabela profiles
    url = f"{SUPABASE_URL}/rest/v1/profiles?user_id=eq.{user_id}&select=*"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {token}"}
    try:
        resp = httpx.get(url, headers=headers)
        data = resp.json()
        if data:
            return data[0]
        # Se não tiver perfil, cria um padrão 'student'
        return {"role": "student", "nome": "Aluno", "user_id": user_id}
    except:
        return {"role": "student", "nome": "Aluno", "user_id": user_id}

# --- FUNÇÕES DE DADOS (SQL) ---
def run_query(query, params=None):
    engine = get_engine()
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params=params)

def execute_statement(statement, params=None):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(statement), params)

# --- UI: TELA DE LOGIN ---
if "auth" not in st.session_state:
    st.session_state.auth = None

if not st.session_state.auth:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("🏋️ App Personal")
        st.markdown("Acesse sua conta para ver treinos e avaliações.")
        
        with st.form("login_form"):
            email = st.text_input("E-mail")
            senha = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar", use_container_width=True)
            
        if submitted:
            data = sb_login(email, senha)
            if data:
                user_id = data["user"]["id"]
                token = data["access_token"]
                profile = get_user_profile(user_id, token)
                
                st.session_state.auth = {
                    "token": token,
                    "user_id": user_id,
                    "email": email,
                    "role": profile.get("role", "student"),
                    "nome": profile.get("nome", "Aluno")
                }
                st.rerun()
            # Se falhar, o erro já será exibido dentro da função sb_login
    st.stop()

# --- UI: APLICAÇÃO PRINCIPAL ---

# Dados do Usuário Logado
user = st.session_state.auth
is_teacher = user["role"] == "teacher"

# Header Mobile
c1, c2 = st.columns([3, 1])
c1.subheader(f"Olá, {user['nome']}")
if c2.button("Sair"):
    st.session_state.auth = None
    st.rerun()

# --- SELEÇÃO DE ALUNO (Apenas Professor) ---
target_user_id = user["user_id"] # Padrão: ver a si mesmo
target_user_name = user["nome"]

if is_teacher:
    with st.expander("👥 Selecionar Aluno (Visão do Professor)", expanded=False):
        # Busca todos os alunos
        try:
            alunos_df = run_query("SELECT * FROM profiles WHERE role = 'student'")
            if not alunos_df.empty:
                aluno_opts = {row["nome"]: row["user_id"] for i, row in alunos_df.iterrows()}
                sel_aluno = st.selectbox("Visualizar dados de:", ["(Eu mesmo)"] + list(aluno_opts.keys()))
                
                if sel_aluno != "(Eu mesmo)":
                    target_user_id = aluno_opts[sel_aluno]
                    target_user_name = sel_aluno
            else:
                st.info("Nenhum aluno cadastrado na tabela profiles.")
        except Exception as e:
            st.error(f"Erro ao buscar alunos: {e}")

# --- ABAS DE NAVEGAÇÃO (Melhor para celular) ---
tab_dash, tab_treino, tab_aval, tab_conta = st.tabs(["📊 Dash", "💪 Treinos", "📏 Avaliação", "⚙️ Conta"])

# =========================================================
# TAB 1: DASHBOARD
# =========================================================
with tab_dash:
    st.caption(f"Visualizando dados de: **{target_user_name}**")
    
    try:
        # Busca última avaliação
        df_av = run_query("""
            SELECT * FROM avaliacoes 
            WHERE user_id = :uid 
            ORDER BY data DESC
        """, {"uid": target_user_id})

        if not df_av.empty:
            last = df_av.iloc[0]
            prev = df_av.iloc[1] if len(df_av) > 1 else None
            
            # Métricas (Cards)
            k1, k2, k3 = st.columns(3)
            
            def safe_delta(curr, prev_val):
                if prev_val is None or pd.isna(prev_val): return None
                return f"{curr - prev_val:.1f}"

            peso_val = float(last['peso']) if pd.notna(last['peso']) else 0.0
            gord_val = float(last['percentual_gordura']) if pd.notna(last['percentual_gordura']) else 0.0
            mm_val = float(last['percentual_massa_magra']) if pd.notna(last['percentual_massa_magra']) else 0.0

            peso_prev = float(prev['peso']) if prev is not None and pd.notna(prev['peso']) else None
            gord_prev = float(prev['percentual_gordura']) if prev is not None and pd.notna(prev['percentual_gordura']) else None
            mm_prev = float(prev['percentual_massa_magra']) if prev is not None and pd.notna(prev['percentual_massa_magra']) else None

            k1.metric("Peso", f"{peso_val} kg", safe_delta(peso_val, peso_prev))
            k2.metric("% Gordura", f"{gord_val}%", safe_delta(gord_val, gord_prev), delta_color="inverse")
            k3.metric("Massa Magra", f"{mm_val}%", safe_delta(mm_val, mm_prev))

            # Gráficos (Plotly Mobile Friendly)
            st.divider()
            if len(df_av) > 1:
                fig = px.line(df_av, x="data", y=["peso", "percentual_gordura"], markers=True, title="Evolução Corporal")
                fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Registre mais avaliações para ver o gráfico de evolução.")
        else:
            st.info("Nenhuma avaliação registrada para este usuário.")
    except Exception as e:
        st.error(f"Erro ao carregar dashboard: {e}")

# =========================================================
# TAB 2: TREINOS
# =========================================================
with tab_treino:
    st.caption(f"Histórico de: **{target_user_name}**")
    
    # Botão de Novo Treino
    with st.expander("➕ Registrar Novo Treino"):
        with st.form("form_treino"):
            d_treino = st.date_input("Data", value=date.today())
            grupo = st.selectbox("Grupo", ["Peito", "Costas", "Pernas", "Ombros", "Bíceps", "Tríceps", "Abdômen", "Cardio"])
            exercicio = st.text_input("Exercício (ex: Supino)")
            
            c_s, c_r, c_k = st.columns(3)
            series = c_s.number_input("Séries", 1, 10, 3)
            reps = c_r.number_input("Reps", 1, 50, 10)
            carga = c_k.number_input("Carga (kg)", 0.0, 500.0, 0.0)
            
            obs = st.text_area("Obs")
            
            if st.form_submit_button("Salvar Treino", use_container_width=True):
                try:
                    execute_statement("""
                        INSERT INTO treinos (user_id, data, grupo_muscular, exercicio, series, repeticoes, carga_kg, observacoes)
                        VALUES (:uid, :dt, :grp, :exc, :ser, :rep, :kg, :obs)
                    """, {
                        "uid": target_user_id, "dt": d_treino, "grp": grupo, "exc": exercicio,
                        "ser": series, "rep": reps, "kg": carga, "obs": obs
                    })
                    st.success("Treino salvo!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

    # Lista de Treinos Recentes
    st.subheader("Últimos Treinos")
    try:
        df_treinos = run_query("""
            SELECT data, grupo_muscular, exercicio, series, repeticoes, carga_kg 
            FROM treinos 
            WHERE user_id = :uid 
            ORDER BY data DESC LIMIT 20
        """, {"uid": target_user_id})
        
        if not df_treinos.empty:
            st.dataframe(df_treinos, use_container_width=True, hide_index=True)
        else:
            st.write("Sem histórico.")
    except Exception as e:
        st.error(f"Erro ao carregar treinos: {e}")

# =========================================================
# TAB 3: AVALIAÇÃO FÍSICA
# =========================================================
with tab_aval:
    if is_teacher:
        with st.expander("➕ Nova Avaliação Física"):
            with st.form("form_aval"):
                dt_av = st.date_input("Data", value=date.today())
                c1, c2 = st.columns(2)
                peso_av = c1.number_input("Peso (kg)", 0.0)
                alt_av = c2.number_input("Altura (m)", 0.0)
                gord_av = c1.number_input("% Gordura", 0.0)
                mm_av = c2.number_input("% Massa Magra", 0.0)
                
                if st.form_submit_button("Salvar Avaliação"):
                    try:
                        execute_statement("""
                            INSERT INTO avaliacoes (user_id, data, peso, altura, percentual_gordura, percentual_massa_magra)
                            VALUES (:uid, :dt, :p, :a, :g, :m)
                        """, {"uid": target_user_id, "dt": dt_av, "p": peso_av, "a": alt_av, "g": gord_av, "m": mm_av})
                        st.success("Avaliação salva!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro ao salvar: {e}")
    else:
        st.info("Apenas professores podem cadastrar avaliações.")
    
    # Tabela detalhada
    st.subheader("Histórico Completo")
    if 'df_av' in locals() and not df_av.empty:
        st.dataframe(df_av, use_container_width=True, hide_index=True)
    else:
        st.write("Nenhuma avaliação.")

# =========================================================
# TAB 4: CONTA E CONFIG
# =========================================================
with tab_conta:
    st.markdown("### Configurações")
    if is_teacher:
        st.success("Logado como: **Professor**")
        st.info("Você tem permissão para ver e editar dados de todos os alunos.")
        st.markdown("---")
        st.markdown("**Como cadastrar um novo aluno:**")
        st.markdown("1. Vá ao painel do Supabase > Authentication > Users > Add User.")
        st.markdown("2. Vá ao Table Editor > profiles > Insira o ID do usuário criado, defina role='student' e o nome.")
    else:
        st.success("Logado como: **Aluno**")
        st.info("Você está visualizando seus próprios dados.")
        
    st.markdown("---")
    if st.button("Sair (Logout)"):
        st.session_state.auth = None
        st.rerun()
"""Sales Analytics App — Streamlit.

Ejecutar con (Windows Anaconda):
    C:\\Users\\brian\\anaconda3\\python.exe -m streamlit run app.py
"""

import pandas as pd
import plotly.express as px
import streamlit as st

from src.data import DATA_PATH, PROCESSED_PATH, REPORTE_PATH, clean, compute_rfm, load_raw, save_processed, vista_comercial

st.set_page_config(page_title="Sales Analytics", layout="wide", page_icon="📊")

ORDEN_DIAS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Sunday", "Saturday"]


@st.cache_data(show_spinner="Cargando y limpiando dataset…")
def get_data():
    import json

    # Si existe cache parquet + reporte, carga directa (rápida)
    if PROCESSED_PATH.exists() and REPORTE_PATH.exists():
        try:
            df_base = load_raw(DATA_PATH)  # devuelve base desde parquet
            reporte = json.loads(REPORTE_PATH.read_text())
            return df_base, reporte
        except Exception:
            pass
    df_raw = load_raw(DATA_PATH)
    df_base, reporte = clean(df_raw)
    if not PROCESSED_PATH.exists():
        try:
            save_processed(df_base)
        except Exception:
            pass
    return df_base, reporte


# ---------------- Carga ----------------
try:
    df_base, reporte = get_data()
except FileNotFoundError:
    st.error(f"No se encontró el dataset en {DATA_PATH}")
    st.stop()

df_com = vista_comercial(df_base)

st.title("📊 Sales Analytics — Online Retail")
st.caption("Limpieza automática aplicada: ajustes internos, duplicados y precios negativos fuera. Vista comercial por defecto.")

with st.expander("🧹 Detalle de limpieza automática", expanded=False):
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Original", f"{reporte['original']:,}")
    c2.metric("Ajustes internos", f"{reporte['ajustes_internos']:,}")
    c3.metric("Cancelaciones (flag)", f"{reporte['cancelaciones']:,}")
    c4.metric("Duplicados", f"{reporte['duplicados']:,}")
    c5.metric("Base limpia", f"{reporte['base']:,}")
    st.caption("Base = original − ajustes − duplicados. La vista comercial además excluye cancelaciones, postage/fees y Quantity/UnitPrice ≤ 0.")

# ---------------- Sidebar ----------------
st.sidebar.header("Filtros")
vista = st.sidebar.radio(
    "Vista",
    ["Ventas comerciales (recomendado)", "Todo (auditoría)"],
    index=0,
)

df_work = df_com if vista.startswith("Ventas") else df_base

dmin, dmax = df_work["InvoiceDate"].min(), df_work["InvoiceDate"].max()
rango = st.sidebar.date_input("Rango de fechas", value=(dmin.date(), dmax.date()), min_value=dmin.date(), max_value=dmax.date())
if isinstance(rango, tuple) and len(rango) == 2:
    f_ini, f_fin = pd.to_datetime(rango[0]), pd.to_datetime(rango[1]) + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    df_work = df_work[(df_work["InvoiceDate"] >= f_ini) & (df_work["InvoiceDate"] <= f_fin)]

paises = sorted(df_work["Country"].dropna().unique())
sel_paises = st.sidebar.multiselect("País", paises, default=paises)
if sel_paises:
    df_work = df_work[df_work["Country"].isin(sel_paises)]

top_n = st.sidebar.slider("Top N (productos / clientes)", 5, 30, 10)

if df_work.empty:
    st.warning("Sin datos para los filtros seleccionados.")
    st.stop()

# ---------------- KPIs ----------------
facturacion = df_work["TotalVenta"].sum()
n_facturas = df_work["InvoiceNo"].nunique()
n_clientes = df_work["CustomerID"].nunique()
unidades = df_work["Quantity"].sum()
ticket = facturacion / n_facturas if n_facturas else 0

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Facturación", f"£{facturacion:,.2f}")
k2.metric("Facturas", f"{n_facturas:,}")
k3.metric("Ticket medio", f"£{ticket:,.2f}")
k4.metric("Clientes", f"{n_clientes:,}")
k5.metric("Unidades", f"{unidades:,.0f}")

tab_res, tab_temp, tab_prod, tab_cli, tab_dat = st.tabs(
    ["📌 Resumen", "📈 Temporal", "📦 Productos", "👥 Clientes / RFM", "🗂️ Datos"]
)

# ---------------- Resumen ----------------
with tab_res:
    col1, col2 = st.columns(2)
    with col1:
        vm = df_work.set_index("InvoiceDate").resample("ME")["TotalVenta"].sum().reset_index()
        vm["Mes"] = vm["InvoiceDate"].dt.strftime("%Y-%m")
        fig = px.line(vm, x="Mes", y="TotalVenta", markers=True, title="Facturación mensual")
        st.plotly_chart(fig, use_container_width=True)
    with col2:
        vp = df_work.groupby("Country")["TotalVenta"].sum().sort_values(ascending=False).head(top_n).reset_index()
        fig = px.bar(vp, x="Country", y="TotalVenta", title=f"Top {top_n} países por facturación")
        st.plotly_chart(fig, use_container_width=True)

# ---------------- Temporal ----------------
with tab_temp:
    df_work["DiaSemana"] = df_work["InvoiceDate"].dt.day_name()
    df_work["Hora"] = df_work["InvoiceDate"].dt.hour
    c1, c2 = st.columns(2)
    with c1:
        vd = df_work.groupby("DiaSemana")["TotalVenta"].sum().reindex(ORDEN_DIAS).dropna().reset_index()
        fig = px.bar(vd, x="DiaSemana", y="TotalVenta", title="Facturación por día de semana")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        vh = df_work.groupby("Hora")["TotalVenta"].sum().reset_index()
        fig = px.line(vh, x="Hora", y="TotalVenta", markers=True, title="Facturación por hora")
        st.plotly_chart(fig, use_container_width=True)
    f_dia = df_work.groupby("DiaSemana")["InvoiceNo"].nunique().reindex(ORDEN_DIAS).dropna()
    t_dia = (df_work.groupby("DiaSemana")["TotalVenta"].sum() / f_dia).reindex(ORDEN_DIAS).dropna().reset_index()
    t_dia.columns = ["Día", "Ticket medio"]
    st.dataframe(t_dia, use_container_width=True)

# ---------------- Productos ----------------
with tab_prod:
    busq = st.text_input("Buscar producto (Description o StockCode)", "")
    dfp = df_work
    if busq:
        b = busq.lower()
        dfp = dfp[dfp["Description"].str.lower().str.contains(b, na=False) | dfp["StockCode"].astype(str).str.lower().str.contains(b)]
    gp = (
        dfp.groupby(["StockCode", "Description"])
        .agg(Facturacion=("TotalVenta", "sum"), Unidades=("Quantity", "sum"), Facturas=("InvoiceNo", "nunique"))
        .reset_index()
        .sort_values("Facturacion", ascending=False)
    )
    c1, c2 = st.columns(2)
    with c1:
        fig = px.bar(gp.head(top_n).sort_values("Facturacion"), x="Facturacion", y="Description", orientation="h", title=f"Top {top_n} por facturación")
        st.plotly_chart(fig, use_container_width=True)
    with c2:
        fig = px.bar(gp.sort_values("Unidades", ascending=False).head(top_n).sort_values("Unidades"), x="Unidades", y="Description", orientation="h", title=f"Top {top_n} por unidades")
        st.plotly_chart(fig, use_container_width=True)
    st.dataframe(gp.head(200), use_container_width=True)

# ---------------- Clientes / RFM ----------------
with tab_cli:
    dfc = df_work[df_work["CustomerID"].notna()]
    if dfc.empty:
        st.info("No hay clientes con ID en esta selección.")
    else:
        gasto = dfc.groupby("CustomerID")["TotalVenta"].sum().sort_values(ascending=False).head(top_n).reset_index()
        fig = px.bar(gasto.sort_values("TotalVenta"), x="TotalVenta", y=gasto["CustomerID"].astype(str), orientation="h", title=f"Top {top_n} clientes por facturación")
        fig.update_layout(yaxis_title="CustomerID")
        st.plotly_chart(fig, use_container_width=True)

        ticket_fac = dfc.groupby(["CustomerID", "InvoiceNo"])["TotalVenta"].sum().reset_index()
        c1, c2 = st.columns(2)
        c1.metric("Ticket medio por factura", f"£{ticket_fac['TotalVenta'].mean():,.2f}")
        c2.metric("Ticket mediano", f"£{ticket_fac['TotalVenta'].median():,.2f}")
        fig = px.histogram(ticket_fac[ticket_fac["TotalVenta"] <= ticket_fac["TotalVenta"].quantile(0.99)], x="TotalVenta", nbins=50, title="Distribución del ticket (hasta p99)")
        st.plotly_chart(fig, use_container_width=True)

        st.subheader("Segmentación RFM")
        with st.spinner("Calculando RFM…"):
            rfm = compute_rfm(dfc)
        if not rfm.empty:
            seg = rfm["Segment"].value_counts().reset_index()
            seg.columns = ["Segmento", "Clientes"]
            c1, c2 = st.columns(2)
            with c1:
                st.plotly_chart(px.bar(seg.sort_values("Clientes"), x="Clientes", y="Segmento", orientation="h", title="Clientes por segmento"), use_container_width=True)
            with c2:
                st.plotly_chart(px.bar(rfm.groupby("Segment")["Monetary"].sum().reset_index().sort_values("Monetary"), x="Monetary", y="Segment", orientation="h", title="Facturación por segmento"), use_container_width=True)
            st.dataframe(rfm.head(200), use_container_width=True)

# ---------------- Datos ----------------
with tab_dat:
    st.subheader("Muestra")
    st.dataframe(df_work.head(200), use_container_width=True)
    st.subheader("Calidad")
    c1, c2 = st.columns(2)
    with c1:
        st.write("Nulos por columna")
        st.dataframe((df_work.isnull().sum().to_frame("Nulos")), use_container_width=True)
    with c2:
        st.write(f"Duplicados en vista: {df_work.duplicated().sum():,}")
        st.write(f"TotalVenta ≤ 0: {(df_work['TotalVenta'] <= 0).sum():,}")
        st.write(f"Quantity < 0: {(df_work['Quantity'] < 0).sum():,}")
    csv = df_work.head(50000).to_csv(index=False).encode("utf-8")
    st.download_button("⬇️ Descargar vista (hasta 50k filas, CSV)", csv, "ventas_vista.csv", "text/csv")

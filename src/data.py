"""Lógica de carga y limpieza del dataset Online Retail.

Replica la limpieza validada en 01_Data_Analysis.ipynb:
- EsCancelacion: InvoiceNo empieza con 'C'
- EsAjusteInterno: Quantity<0, no cancelación, UnitPrice==0, sin CustomerID
  (+ UnitPrice<0 como ajuste contable: 'Adjust bad debt')
- Deduplicación exacta
- EsConceptoNoProducto: POSTAGE, fees, manual, etc.
- TotalVenta = Quantity * UnitPrice
"""

from pathlib import Path
import pandas as pd

CONCEPTOS_NO_PRODUCTO = [
    "POSTAGE",
    "DOTCOM POSTAGE",
    "Adjust bad debt",
    "AMAZON FEE",
    "CRUK Commission",
    "Manual",
    "Bank Charges",
]

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "Online Retail.xlsx"
PROCESSED_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "ventas_base.parquet"
REPORTE_PATH = Path(__file__).resolve().parents[1] / "data" / "processed" / "reporte.json"


def load_raw(path: Path | str = DATA_PATH) -> pd.DataFrame:
    # Cache parquet para arranques rápidos de Streamlit.
    # OJO: el parquet ya guarda la base limpia con flags.
    if PROCESSED_PATH.exists():
        try:
            df = pd.read_parquet(PROCESSED_PATH)
            df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
            return df
        except Exception:
            pass
    df = pd.read_excel(path)
    df["InvoiceDate"] = pd.to_datetime(df["InvoiceDate"])
    return df


def save_processed(df_base: pd.DataFrame, path: Path = PROCESSED_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = df_base.copy()
    out["InvoiceNo"] = out["InvoiceNo"].astype(str)
    out["StockCode"] = out["StockCode"].astype(str)
    out.to_parquet(path, index=False)


def add_flags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EsCancelacion"] = df["InvoiceNo"].astype(str).str.startswith("C")
    df["EsAjusteInterno"] = (
        ((df["Quantity"] < 0) & (~df["EsCancelacion"]) & (df["UnitPrice"] == 0) & (df["CustomerID"].isna()))
        | (df["UnitPrice"] < 0)
    )
    df["EsConceptoNoProducto"] = df["Description"].isin(CONCEPTOS_NO_PRODUCTO)
    df["TotalVenta"] = df["Quantity"] * df["UnitPrice"]
    return df


def clean(df: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    """Aplica limpieza automática. Devuelve (df_base, reporte)."""
    n0 = len(df)
    df = add_flags(df)

    n_ajustes = int(df["EsAjusteInterno"].sum())
    n_cancel = int(df["EsCancelacion"].sum())

    df_base = df[~df["EsAjusteInterno"]].copy()
    dup = int(df_base.duplicated().sum())
    df_base = df_base.drop_duplicates().copy()
    df_base["TotalVenta"] = df_base["Quantity"] * df_base["UnitPrice"]

    reporte = {
        "original": n0,
        "ajustes_internos": n_ajustes,
        "cancelaciones": n_cancel,
        "duplicados": dup,
        "base": len(df_base),
    }
    return df_base, reporte


def vista_comercial(df_base: pd.DataFrame) -> pd.DataFrame:
    """Ventas comerciales: Quantity>0, UnitPrice>0, no cancelación, no concepto."""
    return df_base[
        (df_base["Quantity"] > 0)
        & (df_base["UnitPrice"] > 0)
        & (~df_base["EsCancelacion"])
        & (~df_base["EsConceptoNoProducto"])
    ].copy()


def compute_rfm(df: pd.DataFrame) -> pd.DataFrame:
    """RFM sobre ventas con CustomerID. Robusto a pocos datos (qcut con duplicates='drop')."""
    dfc = df[df["CustomerID"].notna()].copy()
    if dfc.empty:
        return pd.DataFrame()
    ref = dfc["InvoiceDate"].max() + pd.Timedelta(days=1)
    agg = dfc.groupby("CustomerID").agg(
        UltimaCompra=("InvoiceDate", "max"),
        Frequency=("InvoiceNo", "nunique"),
        Monetary=("TotalVenta", "sum"),
    )
    agg["Recency"] = (ref - agg["UltimaCompra"]).dt.days

    def score(s, ascending, labels):
        try:
            return pd.qcut(s.rank(method="first"), 5, labels=labels, duplicates="drop")
        except Exception:
            # fallback: corte uniforme
            return pd.cut(s.rank(method="first"), 5, labels=labels)

    agg["R_score"] = score(agg["Recency"], False, [5, 4, 3, 2, 1])
    agg["F_score"] = score(agg["Frequency"], True, [1, 2, 3, 4, 5])
    agg["M_score"] = score(agg["Monetary"], True, [1, 2, 3, 4, 5])
    agg["RFM_Total"] = agg["R_score"].astype(int) + agg["F_score"].astype(int) + agg["M_score"].astype(int)
    agg["RFM_Score"] = agg["R_score"].astype(str) + agg["F_score"].astype(str) + agg["M_score"].astype(str)
    agg["Segment"] = agg.apply(segmento_rfm, axis=1)
    return agg.sort_values("Monetary", ascending=False)


def segmento_rfm(row) -> str:
    R, F, M = int(row["R_score"]), int(row["F_score"]), int(row["M_score"])
    if R >= 4 and F >= 4 and M >= 4:
        return "Champions"
    if R >= 3 and F >= 4 and M >= 3:
        return "Loyal"
    if R >= 4 and F <= 2:
        return "New / Promising"
    if R <= 2 and F >= 3:
        return "At Risk"
    if R <= 2 and F <= 2:
        return "Lost / Inactive"
    return "Needs Attention"

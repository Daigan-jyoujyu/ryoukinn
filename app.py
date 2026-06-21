from pathlib import Path
import hmac
import os

import pandas as pd
import streamlit as st


BASE_DIR = Path(__file__).resolve().parent
APP_TITLE = "サービス料金シュミレーター"
REGIONAL_UNIT_PRICE = 10.72
CAFE_PRICE_PER_VISIT = 250

VISIT_COUNTS = {
    "週1回": 4,
    "週2回": 9,
    "週3回": 13,
    "週4回": 17,
    "週5回": 22,
    "週6回": 26,
}

CARE_LEVEL_BASE_UNITS = {
    "要介護1": 416,
    "要介護2": 478,
    "要介護3": 540,
    "要介護4": 600,
    "要介護5": 663,
}

BURDEN_RATES = {
    "1割": 0.1,
    "2割": 0.2,
    "3割": 0.3,
}

CARE_ADDITIONS = [
    {"name": "個別機能訓練加算Ⅰ1", "units": 56, "kind": "per_visit", "note": "1回ごと"},
    {"name": "個別機能訓練加算Ⅱ", "units": 20, "kind": "monthly", "note": "月1回"},
    {"name": "科学的介護推進体制加算", "units": 40, "kind": "monthly", "note": "月1回"},
    {"name": "ADL維持等加算Ⅰ", "units": 30, "kind": "monthly", "note": "月1回"},
    {"name": "ADL維持等加算Ⅱ", "units": 60, "kind": "monthly", "note": "月1回"},
    {"name": "サービス提供体制強化加算Ⅲ", "units": 6, "kind": "per_visit", "note": "1回ごと"},
]

SUPPORT_CARE_SERVICE_CODES = {
    "事業対象者": {
        "base": "1111",
        "treatment": "6189",
        "additions": [
            {"key": "service_strength_3", "label": "サービス提供体制強化加算Ⅲ", "code": "6103", "kind": "monthly"},
            {"key": "science", "label": "科学的介護推進体制加算", "code": "6311", "kind": "monthly"},
        ],
    },
    "要支援1": {
        "base": "1111",
        "treatment": "6189",
        "additions": [
            {"key": "service_strength_3", "label": "サービス提供体制強化加算Ⅲ", "code": "6103", "kind": "monthly"},
            {"key": "science", "label": "科学的介護推進体制加算", "code": "6311", "kind": "monthly"},
        ],
    },
    "要支援2（週1回程度）": {
        "base": "1221",
        "treatment": "6189",
        "additions": [
            {"key": "service_strength_3", "label": "サービス提供体制強化加算Ⅲ", "code": "6124", "kind": "monthly"},
            {"key": "science", "label": "科学的介護推進体制加算", "code": "6321", "kind": "monthly"},
        ],
    },
    "要支援2（週2回程度）": {
        "base": "1121",
        "treatment": "6189",
        "additions": [
            {"key": "service_strength_3", "label": "サービス提供体制強化加算Ⅲ", "code": "6104", "kind": "monthly"},
            {"key": "science", "label": "科学的介護推進体制加算", "code": "6311", "kind": "monthly"},
        ],
    },
}


st.set_page_config(page_title=APP_TITLE, page_icon="💴", layout="wide")


def get_app_password() -> str:
    try:
        secret_password = str(st.secrets.get("APP_PASSWORD", ""))
    except Exception:
        secret_password = ""
    return secret_password or os.environ.get("APP_PASSWORD", "")


def require_password() -> None:
    configured_password = get_app_password()

    if not configured_password:
        st.error("このアプリを使うには、管理者用パスワードの設定が必要です。")
        st.info("Streamlit CloudのSecrets、またはローカルの .streamlit/secrets.toml に APP_PASSWORD を設定してください。")
        st.stop()

    if st.session_state.get("password_ok"):
        return

    st.title(APP_TITLE)
    st.subheader("ログイン")
    entered_password = st.text_input("パスワード", type="password")

    if st.button("開く"):
        if hmac.compare_digest(entered_password, configured_password):
            st.session_state["password_ok"] = True
            st.rerun()
        else:
            st.error("パスワードが違います。")

    st.stop()


def yen(value: float) -> str:
    return f"{round(value):,} 円"


def load_csv_with_fallback(path: Path) -> pd.DataFrame:
    encodings = ["utf-8-sig", "cp932", "shift_jis", "utf-8"]
    last_error = None
    for encoding in encodings:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error


def load_raw_csv_with_fallback(path: Path) -> pd.DataFrame:
    encodings = ["utf-8-sig", "cp932", "shift_jis", "utf-8"]
    last_error = None
    for encoding in encodings:
        try:
            return pd.read_csv(path, encoding=encoding, header=None, dtype=str)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error


@st.cache_data
def load_a6_master() -> pd.DataFrame:
    path = BASE_DIR / "20260601masuta_0522.csv"
    if not path.exists():
        return pd.DataFrame()

    df = load_raw_csv_with_fallback(path)
    if df.shape[1] < 7:
        return pd.DataFrame()

    current_df = df[
        (df[1] == "A6")
        & (df[3].astype(int) <= 202606)
        & (df[4].astype(int) >= 202606)
    ].copy()
    current_df = current_df.rename(
        columns={
            1: "service_type",
            2: "code",
            5: "name",
            6: "units",
        }
    )
    current_df["units"] = current_df["units"].astype(int)
    return current_df[["service_type", "code", "name", "units"]]


def get_a6_service(master_df: pd.DataFrame, code: str) -> dict[str, object]:
    if master_df.empty:
        raise ValueError("A6サービスコード表CSVが見つかりません。")

    rows = master_df[master_df["code"] == code]
    if rows.empty:
        raise ValueError(f"A6サービスコード {code} がCSVに見つかりません。")

    row = rows.iloc[0]
    return {
        "service_code": f"{row['service_type']}{row['code']}",
        "name": row["name"],
        "units": int(row["units"]),
    }


def load_uploaded_csv_with_fallback(uploaded_file) -> pd.DataFrame:
    encodings = ["utf-8-sig", "cp932", "shift_jis", "utf-8"]
    last_error = None
    raw_data = uploaded_file.getvalue()
    for encoding in encodings:
        try:
            return pd.read_csv(pd.io.common.BytesIO(raw_data), encoding=encoding)
        except UnicodeDecodeError as exc:
            last_error = exc
    raise last_error


def find_column(columns: list[str], keywords: list[str]) -> str | None:
    for column in columns:
        normalized = str(column).replace(" ", "").replace("　", "")
        if all(keyword in normalized for keyword in keywords):
            return column
    return None


def normalize_service_code(value: object) -> str:
    if pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        text = text[:-2]
    return text


def prepare_a6_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str | None]]:
    columns = [str(column) for column in df.columns]
    column_map = {
        "code": find_column(columns, ["サービス", "コード"]) or find_column(columns, ["コード"]),
        "name": find_column(columns, ["サービス", "名称"]) or find_column(columns, ["名称"]),
        "units": find_column(columns, ["単位"]),
    }

    working = df.copy()
    if column_map["code"]:
        working["_service_code_text"] = working[column_map["code"]].map(normalize_service_code)
        working = working[working["_service_code_text"].str.startswith("A6", na=False)]

    display_columns = [column for column in column_map.values() if column]
    if display_columns:
        working = working[display_columns].copy()

    return working, column_map


def calculate_care_cost(
    care_level: str,
    visit_count: int,
    burden_rate: float,
    selected_additions: dict[str, bool],
    include_treatment_improvement: bool,
    include_cafe: bool,
) -> dict[str, object]:
    rows = []
    base_unit = CARE_LEVEL_BASE_UNITS[care_level]
    base_subtotal = base_unit * visit_count
    rows.append(
        {
            "項目": f"{care_level} 基本サービス",
            "単位数": base_unit,
            "回数": visit_count,
            "小計単位": base_subtotal,
            "備考": "地域密着型通所介護 3時間以上4時間未満",
        }
    )

    addition_total = 0
    for addition in CARE_ADDITIONS:
        if not selected_additions.get(addition["name"], False):
            continue

        count = visit_count if addition["kind"] == "per_visit" else 1
        subtotal = addition["units"] * count
        addition_total += subtotal
        rows.append(
            {
                "項目": addition["name"],
                "単位数": addition["units"],
                "回数": count,
                "小計単位": subtotal,
                "備考": addition["note"],
            }
        )

    prescribed_units = base_subtotal + addition_total
    treatment_units = round(prescribed_units * 0.105) if include_treatment_improvement else 0
    if include_treatment_improvement:
        rows.append(
            {
                "項目": "介護職員等処遇改善加算Ⅲ",
                "単位数": "10.5%",
                "回数": 1,
                "小計単位": treatment_units,
                "備考": "所定単位数 × 10.5%",
            }
        )

    total_units = prescribed_units + treatment_units
    insurance_cost = total_units * REGIONAL_UNIT_PRICE * burden_rate
    out_of_pocket = CAFE_PRICE_PER_VISIT * visit_count if include_cafe else 0
    total_cost = round(insurance_cost) + out_of_pocket

    return {
        "rows": rows,
        "base_units": base_subtotal,
        "addition_units": addition_total,
        "treatment_units": treatment_units,
        "total_units": total_units,
        "insurance_cost": round(insurance_cost),
        "out_of_pocket": out_of_pocket,
        "total_cost": total_cost,
    }


def calculate_support_cost(
    support_level: str,
    visit_count: int,
    burden_rate: float,
    selected_additions: dict[str, bool],
    include_treatment_improvement: bool,
    include_cafe: bool,
    master_df: pd.DataFrame,
) -> dict[str, object]:
    service_codes = SUPPORT_CARE_SERVICE_CODES[support_level]
    base_service = get_a6_service(master_df, service_codes["base"])

    rows = []
    base_subtotal = base_service["units"]
    rows.append(
        {
            "項目": f"{support_level} 基本サービス",
            "サービスコード": base_service["service_code"],
            "単位数": base_service["units"],
            "回数": 1,
            "小計単位": base_subtotal,
            "備考": f"{base_service['name']} / 1月につき",
        }
    )

    addition_total = 0
    for addition in service_codes["additions"]:
        if not selected_additions.get(addition["key"], False):
            continue

        if addition["code"] is None:
            continue

        service = get_a6_service(master_df, addition["code"])
        count = 1
        subtotal = service["units"] * count
        addition_total += subtotal
        rows.append(
            {
                "項目": addition["label"],
                "サービスコード": service["service_code"],
                "単位数": service["units"],
                "回数": count,
                "小計単位": subtotal,
                "備考": f"{service['name']} / 1月につき",
            }
        )

    prescribed_units = base_subtotal + addition_total
    treatment_units = round(prescribed_units * 0.105) if include_treatment_improvement else 0
    if include_treatment_improvement:
        treatment_service = get_a6_service(master_df, service_codes["treatment"])
        rows.append(
            {
                "項目": "処遇改善加算Ⅲ",
                "サービスコード": treatment_service["service_code"],
                "単位数": "10.5%",
                "回数": 1,
                "小計単位": treatment_units,
                "備考": f"{treatment_service['name']} / 所定単位数 × 10.5%",
            }
        )

    total_units = prescribed_units + treatment_units
    insurance_cost = total_units * REGIONAL_UNIT_PRICE * burden_rate
    out_of_pocket = CAFE_PRICE_PER_VISIT * visit_count if include_cafe else 0
    total_cost = round(insurance_cost) + out_of_pocket

    return {
        "rows": rows,
        "base_units": base_subtotal,
        "addition_units": addition_total,
        "treatment_units": treatment_units,
        "total_units": total_units,
        "insurance_cost": round(insurance_cost),
        "out_of_pocket": out_of_pocket,
        "total_cost": total_cost,
    }


def render_visit_count_selector() -> tuple[str, int, str]:
    st.sidebar.subheader("利用回数")
    calculation_method = st.sidebar.radio(
        "計算方法を選択",
        ["週の利用パターンで計算する", "月の利用回数で計算する"],
    )

    if calculation_method == "週の利用パターンで計算する":
        frequency_label = st.sidebar.radio("週の利用パターン", list(VISIT_COUNTS.keys()), index=2)
        visit_count = VISIT_COUNTS[frequency_label]
        return calculation_method, visit_count, f"{frequency_label}（月{visit_count}回）"

    visit_count = st.sidebar.selectbox("月の利用回数", list(range(1, 32)), format_func=lambda count: f"月{count}回")
    return calculation_method, visit_count, f"月{visit_count}回"


require_password()

st.title(APP_TITLE)

with st.sidebar:
    st.header("条件")
    user_type = st.radio("利用者区分", ["要介護", "要支援"], horizontal=True)

    if user_type == "要介護":
        care_level = st.selectbox("介護度", list(CARE_LEVEL_BASE_UNITS.keys()))
    else:
        care_level = st.selectbox("介護度", list(SUPPORT_CARE_SERVICE_CODES.keys()))

    burden_label = st.selectbox("負担割合", list(BURDEN_RATES.keys()))
    include_cafe = st.checkbox("カフェ代 250円/回", value=False)

calculation_method, visit_count, visit_count_label = render_visit_count_selector()
burden_rate = BURDEN_RATES[burden_label]

if user_type == "要介護":
    st.subheader("加算")
    col1, col2 = st.columns(2)
    selected_additions = {}
    for index, addition in enumerate(CARE_ADDITIONS):
        target_col = col1 if index % 2 == 0 else col2
        selected_additions[addition["name"]] = target_col.checkbox(
            f"{addition['name']}（{addition['units']}単位）",
            value=True,
        )

    include_treatment_improvement = st.checkbox(
        "介護職員等処遇改善加算Ⅲ（所定単位数 × 10.5%）",
        value=True,
    )

    result = calculate_care_cost(
        care_level=care_level,
        visit_count=visit_count,
        burden_rate=burden_rate,
        selected_additions=selected_additions,
        include_treatment_improvement=include_treatment_improvement,
        include_cafe=include_cafe,
    )

    st.subheader("計算結果")
    st.caption(f"計算方法: {calculation_method} / 利用回数: {visit_count_label}")
    metric_cols = st.columns(4)
    metric_cols[0].metric("月の目安利用回数", f"{visit_count} 回")
    metric_cols[1].metric("総単位数", f"{result['total_units']:,} 単位")
    metric_cols[2].metric("介護保険自己負担額", yen(result["insurance_cost"]))
    metric_cols[3].metric("合計目安金額", yen(result["total_cost"]))

    detail_cols = st.columns(4)
    detail_cols[0].metric("基本単位", f"{result['base_units']:,} 単位")
    detail_cols[1].metric("加算単位", f"{result['addition_units']:,} 単位")
    detail_cols[2].metric("処遇改善加算単位", f"{result['treatment_units']:,} 単位")
    detail_cols[3].metric("保険外サービス費", yen(result["out_of_pocket"]))

    st.subheader("内訳")
    st.dataframe(pd.DataFrame(result["rows"]), use_container_width=True, hide_index=True)

else:
    a6_master_df = load_a6_master()
    if a6_master_df.empty:
        st.error("A6サービスコード表CSVが見つかりません。20260601masuta_0522.csv をアプリと同じフォルダに配置してください。")
        st.stop()

    st.subheader("加算")
    selected_support_additions = {}
    support_services = SUPPORT_CARE_SERVICE_CODES[care_level]
    for addition in support_services["additions"]:
        if addition["code"] is None:
            st.checkbox(
                f"{addition['label']}（CSVに該当コードなし）",
                value=False,
                disabled=True,
                key=f"support_{care_level}_{addition['key']}_missing",
            )
            selected_support_additions[addition["key"]] = False
            continue

        service = get_a6_service(a6_master_df, addition["code"])
        selected_support_additions[addition["key"]] = st.checkbox(
            f"{addition['label']}（{service['units']}単位 / {service['service_code']}）",
            value=True,
            key=f"support_{care_level}_{addition['key']}",
        )

    include_support_treatment = st.checkbox(
        "処遇改善加算Ⅲ（所定単位数 × 10.5%）",
        value=True,
        key=f"support_{care_level}_treatment",
    )

    result = calculate_support_cost(
        support_level=care_level,
        visit_count=visit_count,
        burden_rate=burden_rate,
        selected_additions=selected_support_additions,
        include_treatment_improvement=include_support_treatment,
        include_cafe=include_cafe,
        master_df=a6_master_df,
    )

    st.subheader("計算結果")
    st.caption(f"計算方法: {calculation_method} / 利用回数: {visit_count_label}")
    metric_cols = st.columns(4)
    metric_cols[0].metric("月の目安利用回数", f"{visit_count} 回")
    metric_cols[1].metric("総単位数", f"{result['total_units']:,} 単位")
    metric_cols[2].metric("介護保険自己負担額", yen(result["insurance_cost"]))
    metric_cols[3].metric("合計目安金額", yen(result["total_cost"]))

    detail_cols = st.columns(4)
    detail_cols[0].metric("基本単位", f"{result['base_units']:,} 単位")
    detail_cols[1].metric("加算単位", f"{result['addition_units']:,} 単位")
    detail_cols[2].metric("処遇改善加算単位", f"{result['treatment_units']:,} 単位")
    detail_cols[3].metric("保険外サービス費", yen(result["out_of_pocket"]))

    st.subheader("内訳")
    st.dataframe(pd.DataFrame(result["rows"]), use_container_width=True, hide_index=True)

    with st.expander("A6サービスコード確認"):
        st.dataframe(a6_master_df, use_container_width=True, hide_index=True)

st.divider()
st.caption(
    "この金額は概算です。実際の請求額は端数処理、給付管理、利用実績、加算算定状況等により変動する場合があります。"
)

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


def render_visit_count_selector() -> tuple[str, list[int]]:
    st.sidebar.subheader("利用回数")
    selection_mode = st.sidebar.radio(
        "利用回数の指定方法",
        ["利用頻度から選ぶ", "任意の利用回数を選択"],
    )

    if selection_mode == "利用頻度から選ぶ":
        frequency_label = st.sidebar.selectbox("利用頻度", list(VISIT_COUNTS.keys()), index=2)
        return selection_mode, [VISIT_COUNTS[frequency_label]]

    st.subheader("利用回数を選択")
    st.caption("1回〜31回まで、必要な回数を選んでください。複数選ぶと回数ごとの料金を一覧表示します。")

    selected_counts = []
    checkbox_columns = st.columns(4)
    for count in range(1, 32):
        target_column = checkbox_columns[(count - 1) % len(checkbox_columns)]
        if target_column.checkbox(f"{count}回", key=f"custom_visit_count_{count}"):
            selected_counts.append(count)

    return selection_mode, selected_counts


require_password()

st.title(APP_TITLE)

with st.sidebar:
    st.header("条件")
    user_type = st.radio("利用者区分", ["要介護", "要支援"], horizontal=True)

    if user_type == "要介護":
        care_level = st.selectbox("介護度", list(CARE_LEVEL_BASE_UNITS.keys()))
    else:
        care_level = st.selectbox("介護度", ["要支援1", "要支援2"])

    burden_label = st.selectbox("負担割合", list(BURDEN_RATES.keys()))
    include_cafe = st.checkbox("カフェ代 250円/回", value=False)

selection_mode, selected_visit_counts = render_visit_count_selector()
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

    if not selected_visit_counts:
        st.warning("利用回数を1つ以上選択してください。")
        st.stop()

    calculation_results = {
        visit_count: calculate_care_cost(
            care_level=care_level,
            visit_count=visit_count,
            burden_rate=burden_rate,
            selected_additions=selected_additions,
            include_treatment_improvement=include_treatment_improvement,
            include_cafe=include_cafe,
        )
        for visit_count in selected_visit_counts
    }

    primary_visit_count = selected_visit_counts[0]
    result = calculation_results[primary_visit_count]

    st.subheader("計算結果")
    if len(selected_visit_counts) == 1:
        metric_cols = st.columns(4)
        metric_cols[0].metric("月の目安利用回数", f"{primary_visit_count} 回")
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
        summary_rows = []
        for visit_count, summary_result in calculation_results.items():
            summary_rows.append(
                {
                    "利用回数": f"{visit_count}回",
                    "基本単位": summary_result["base_units"],
                    "加算単位": summary_result["addition_units"],
                    "処遇改善加算単位": summary_result["treatment_units"],
                    "総単位数": summary_result["total_units"],
                    "介護保険自己負担額": yen(summary_result["insurance_cost"]),
                    "保険外サービス費": yen(summary_result["out_of_pocket"]),
                    "合計目安金額": yen(summary_result["total_cost"]),
                }
            )

        st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

        st.subheader("回数ごとの内訳")
        for visit_count, detail_result in calculation_results.items():
            with st.expander(f"{visit_count}回利用の場合: {yen(detail_result['total_cost'])}"):
                st.dataframe(pd.DataFrame(detail_result["rows"]), use_container_width=True, hide_index=True)

else:
    st.subheader("要支援 A6コード確認")
    st.info("要支援側は、CSVからA6コード・名称・単位数を確認する画面です。計算は次の段階で実装できます。")

    uploaded_file = st.file_uploader("A6コードを含むCSVをアップロード", type=["csv"])
    candidate_paths = [BASE_DIR / "20260601masuta_0522.csv", BASE_DIR / "service_codes.csv"]

    source_label = None
    a6_source_df = None
    if uploaded_file is not None:
        a6_source_df = load_uploaded_csv_with_fallback(uploaded_file)
        source_label = uploaded_file.name
    else:
        for candidate_path in candidate_paths:
            if candidate_path.exists():
                a6_source_df = load_csv_with_fallback(candidate_path)
                source_label = candidate_path.name
                break

    if a6_source_df is None:
        st.warning("CSVが見つかりません。20260601masuta_0522.csv または service_codes.csv を配置してください。")
    else:
        a6_df, column_map = prepare_a6_dataframe(a6_source_df)
        st.caption(f"読込元: {source_label}")

        search_text = st.text_input("名称・コードで絞り込み", value="")
        filtered_df = a6_df
        if search_text:
            mask = filtered_df.astype(str).apply(
                lambda row: row.str.contains(search_text, case=False, na=False).any(),
                axis=1,
            )
            filtered_df = filtered_df[mask]

        st.dataframe(filtered_df, use_container_width=True, hide_index=True)
        st.caption(
            f"検出列: コード={column_map['code'] or '未検出'} / "
            f"名称={column_map['name'] or '未検出'} / 単位数={column_map['units'] or '未検出'}"
        )

st.divider()
st.caption(
    "この金額は概算です。実際の請求額は端数処理、給付管理、利用実績、加算算定状況等により変動する場合があります。"
)

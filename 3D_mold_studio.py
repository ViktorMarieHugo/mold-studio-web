from __future__ import annotations

import streamlit as st

from mold_generator import (
    MoldGenerationError,
    MoldKit,
    extension_from_name,
    generate_mold_kit,
)


@st.cache_data(max_entries=4, show_spinner=False)
def generate_cached(
    file_bytes: bytes,
    file_type: str,
    silicone_thickness: int,
    plastic_wall: int,
) -> MoldKit:
    return generate_mold_kit(
        file_bytes=file_bytes,
        file_type=file_type,
        silicone_thickness=float(silicone_thickness),
        plastic_wall=float(plastic_wall),
    )


st.set_page_config(
    page_title="Irivek3Dstudio — силиконовые формы",
    page_icon=":material/deployed_code:",
    layout="wide",
)

st.session_state.setdefault("mold_kit", None)
st.session_state.setdefault("mold_kit_name", "silicone_mold_kit.zip")

st.title("Irivek3Dstudio")
st.caption(
    "Генератор 3D-печатной оснастки для цельной силиконовой формы открытого типа"
)

settings_column, result_column = st.columns([1, 1.35], gap="large")

with settings_column:
    with st.container(border=True):
        st.subheader("Параметры формы")
        with st.form("mold_settings"):
            uploaded_file = st.file_uploader(
                "Мастер-модель",
                type=["stl", "3mf"],
                max_upload_size=100,
                help="Модель должна быть замкнутой, ориентированной вертикально и иметь плоское основание. STL читается в миллиметрах.",
                key="master_model",
            )
            silicone_thickness = st.slider(
                "Минимальная толщина силикона, мм",
                min_value=5,
                max_value=30,
                value=10,
                step=1,
                key="silicone_thickness",
            )
            plastic_wall = st.slider(
                "Толщина пластиковой опалубки, мм",
                min_value=2,
                max_value=10,
                value=3,
                step=1,
                key="plastic_wall",
            )
            st.caption(
                "Широкое квадратное основание формируется автоматически: "
                "силиконовая форма будет устойчиво стоять на столе."
            )
            submitted = st.form_submit_button(
                "Сгенерировать комплект",
                type="primary",
                icon=":material/build:",
                width="stretch",
            )

        st.caption(
            "Оснастка состоит из пуансона и двух половин опалубки. "
            "Планка оставляет свободные окна для заливки силикона."
        )

with result_column:
    result_slot = st.container(border=True)

if submitted:
    if uploaded_file is None:
        st.session_state.mold_kit = None
        result_slot.error("Сначала загрузите мастер-модель STL или 3MF.")
    else:
        output_name = f"{uploaded_file.name.rsplit('.', 1)[0]}_mold_kit.zip"
        try:
            with result_slot.status(
                "Проверяем модель и строим оснастку…",
                expanded=True,
            ) as status:
                status.write("Проверяем замкнутость и плоское основание")
                status.write(
                    "Строим экономичную оболочку и широкое квадратное основание"
                )
                status.write("Разделяем опалубку, добавляем фланцы и замки")
                kit = generate_cached(
                    uploaded_file.getvalue(),
                    extension_from_name(uploaded_file.name),
                    silicone_thickness,
                    plastic_wall,
                )
                status.update(
                    label="Комплект готов",
                    state="complete",
                    expanded=False,
                )
            st.session_state.mold_kit = kit
            st.session_state.mold_kit_name = output_name
        except MoldGenerationError as exc:
            st.session_state.mold_kit = None
            result_slot.error(str(exc))
        except Exception as exc:
            st.session_state.mold_kit = None
            result_slot.error(f"Не удалось построить оснастку: {exc}")

kit = st.session_state.mold_kit
if kit is not None:
    result_slot.subheader("Готовый комплект")
    with result_slot.container(horizontal=True, gap="small"):
        st.metric(
            "Расход силикона",
            f"≈ {kit.silicone_volume_ml:.0f} мл",
            border=True,
        )
        st.metric(
            "Размер формы",
            " × ".join(f"{value:.0f}" for value in kit.mold_size_mm) + " мм",
            border=True,
        )
        st.metric("Файлы", "3 STL", border=True)

    result_slot.download_button(
        "Скачать ZIP-комплект",
        data=kit.zip_bytes,
        file_name=st.session_state.mold_kit_name,
        mime="application/zip",
        type="primary",
        icon=":material/download:",
        width="stretch",
        on_click="ignore",
    )
    result_slot.caption(
        f"Исходная модель: {kit.source_faces:,} треугольников. "
        f"Расчётная оболочка: {kit.tooling_faces:,} треугольников. "
        f"Оценочный объём пластика: {kit.plastic_volume_ml:.0f} см³."
    )
elif not submitted:
    result_slot.info(
        "Загрузите модель и задайте две толщины. "
        "Здесь появятся расчёт расхода и ZIP из трёх STL-файлов."
    )

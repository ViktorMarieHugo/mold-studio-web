import streamlit as st
import trimesh
import tempfile
import os

st.set_page_config(page_title="Генератор молдов", layout="wide")
st.title("🧱 Генератор силиконовых форм (Молдов)")

# Версия и дата обновления
st.caption("Версия 1.2 (поддержка STL и 3MF) | Обновлено: 23 августа 2026 г.")
st.markdown("---")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Настройки формы")
    
    # Загрузчик теперь принимает и STL, и 3MF
    uploaded_file = st.file_uploader("Загрузите мастер-модель", type=["stl", "3mf"])
    
    st.markdown("---")
    scale_option = st.radio(
        "Масштаб (для 3MF обычно не требуется)",
        [1.0, 10.0, 25.4],
        format_func=lambda x: "Без изменений (x1)" if x == 1.0 else ("Из Сантиметров в Миллиметры (x10)" if x == 10.0 else "Из Дюймов в Миллиметры (x25.4)")
    )
    st.markdown("---")
    
    wall_thickness = st.slider("Толщина стенок формы (мм)", min_value=2, max_value=15, value=5, step=1)
    bottom_offset = st.slider("Толщина дна молда (мм)", min_value=1, max_value=10, value=3, step=1)

with col2:
    st.subheader("Обработка и результат")
    
    if uploaded_file is not None:
        st.success(f"Файл '{uploaded_file.name}' загружен!")
        
        if st.button("Сгенерировать молд (Вычитание)", type="primary"):
            with st.spinner("Анализ геометрии и булево вычитание..."):
                
                # Определяем расширение файла (.stl или .3mf)
                file_extension = os.path.splitext(uploaded_file.name)[1].lower()
                
                # Сохраняем во временную папку с оригинальным расширением
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_file_path = tmp_file.name
                
                try:
                    # Загрузка через trimesh
                    mesh = trimesh.load(tmp_file_path)
                    
                    # Если внутри 3MF было несколько тел, объединяем в один меш
                    if isinstance(mesh, trimesh.Scene):
                        mesh = mesh.dump(concatenate=True)
                    
                    if not isinstance(mesh, trimesh.Trimesh):
                        st.error("Ошибка: Файл не содержит корректную 3D-геометрию.")
                        st.stop()
                    
                    # Применяем масштаб
                    if scale_option != 1.0:
                        mesh.apply_scale(scale_option)
                         
                    extents = mesh.extents 
                    
                    st.write(f"**Актуальные размеры модели (X, Y, Z):** {extents[0]:.1f} x {extents[1]:.1f} x {extents[2]:.1f} мм")
                    
                    # 1. Центрируем мастер-модель строго в начале координат (0,0,0)
                    bounds_center = (mesh.bounds[0] + mesh.bounds[1]) / 2.0
                    mesh.apply_translation(-bounds_center)
                    
                    # 2. Создаем коробку-опалубку
                    box_x = extents[0] + (wall_thickness * 2)
                    box_y = extents[1] + (wall_thickness * 2)
                    box_z = extents[2] + bottom_offset
                    mold_box = trimesh.creation.box(extents=[box_x, box_y, box_z])
                    
                    # 3. Выравниваем коробку по высоте относительно дна
                    mold_box.apply_translation([0, 0, -bottom_offset / 2])
                    
                    # 4. Небольшое смещение вверх, чтобы гарантированно прорезать верхнюю плоскость
                    mesh.apply_translation([0, 0, 0.05])
                    
                    # 5. Булево вычитание через engine='manifold'
                    final_mold = trimesh.boolean.difference([mold_box, mesh], engine='manifold')
                    
                    # Проверка корректности вычитания
                    if abs(final_mold.volume - mold_box.volume) < 0.1:
                        st.error("⚠️ Булево вычитание не смогло вырезать полость. Проверьте геометрию исходной модели.")
                    else:
                        st.success("✅ Молд с полостью успешно создан!")
                    
                    # Экспорт готового молда
                    final_data = final_mold.export(file_type='stl')
                    
                    st.download_button(
                        label="Скачать молд (STL)",
                        data=final_data,
                        file_name="mold_with_cavity.stl",
                        mime="model/stl"
                    )

                except Exception as e:
                    st.error(f"Произошла ошибка при обработке: {e}")
                
                finally:
                    if os.path.exists(tmp_file_path):
                        os.remove(tmp_file_path)
    else:
        st.info("👈 Загрузите модель (.stl или .3mf) в меню слева.")
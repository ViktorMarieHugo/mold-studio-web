import streamlit as st
import trimesh
import tempfile
import os
import math
import zipfile
import io

st.set_page_config(page_title="Генератор молдов", layout="wide")
st.title("🧱 Генератор силиконовых форм (Молдов)")

st.caption("Версия 2.1 (Два режима: цельный и из 2 половинок) | Обновлено: 23 августа 2026 г.")
st.markdown("---")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Настройки формы")
    uploaded_file = st.file_uploader("Загрузите мастер-модель", type=["stl", "3mf"])
    
    st.markdown("---")
    mold_type = st.radio(
        "Конструкция молда:",
        ["Цельный цилиндр (для резки с замками в слайсере)", 
         "Разрезать на 2 половинки (для стяжки струбцинами)"]
    )
    st.markdown("---")
    
    scale_option = st.radio(
        "Масштаб",
        [1.0, 10.0, 25.4],
        format_func=lambda x: "Без изменений (x1)" if x == 1.0 else ("Из Сантиметров (x10)" if x == 10.0 else "Из Дюймов (x25.4)")
    )
    st.markdown("---")
    
    wall_thickness = st.slider("Толщина стенок цилиндра (мм)", min_value=2, max_value=15, value=5, step=1)
    bottom_offset = st.slider("Толщина дна молда (мм)", min_value=1, max_value=10, value=3, step=1)
    sprue_diam = st.slider("Диаметр отверстия для заливки (мм)", min_value=0, max_value=20, value=8, step=1)

with col2:
    st.subheader("Обработка и результат")
    
    if uploaded_file is not None:
        if st.button("Сгенерировать молд", type="primary"):
            with st.spinner("Создание формы и математические расчеты (это может занять минутку)..."):
                
                file_extension = os.path.splitext(uploaded_file.name)[1].lower()
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_file_path = tmp_file.name
                
                try:
                    loaded_data = trimesh.load(tmp_file_path)
                    
                    if isinstance(loaded_data, trimesh.Scene):
                        mesh = loaded_data.dump(concatenate=True)
                    else:
                        mesh = loaded_data
                    
                    if scale_option != 1.0:
                        mesh.apply_scale(scale_option)
                         
                    extents = mesh.extents 
                    st.write(f"**Размеры мастер-модели (X, Y, Z):** {extents[0]:.1f} x {extents[1]:.1f} x {extents[2]:.1f} мм")
                    
                    # 1. Центрируем модель
                    bounds_center = (mesh.bounds[0] + mesh.bounds[1]) / 2.0
                    mesh.apply_translation(-bounds_center)
                    
                    # 2. Создаем цилиндрическую опалубку
                    radius = math.sqrt((extents[0]/2)**2 + (extents[1]/2)**2) + wall_thickness
                    height = extents[2] + bottom_offset + 3.0 
                    
                    mold_cylinder = trimesh.creation.cylinder(radius=radius, height=height)
                    mold_cylinder.apply_translation([0, 0, -bottom_offset / 2 + 1.5])
                    
                    # 3. Литник (канал для заливки)
                    if sprue_diam > 0:
                        sprue = trimesh.creation.cylinder(radius=sprue_diam/2.0, height=extents[2] + 20)
                        sprue.apply_translation([0, 0, extents[2]/2 + 5])
                        mesh_to_subtract = trimesh.boolean.union([mesh, sprue], engine='manifold')
                    else:
                        mesh_to_subtract = mesh
                    
                    mesh_to_subtract.apply_translation([0, 0, 0.05])
                    
                    # 4. Вырезаем модель из цилиндра
                    final_mold = trimesh.boolean.difference([mold_cylinder, mesh_to_subtract], engine='manifold')
                    
                    # 5. Проверяем режим: резать или не резать
                    if "Разрезать на 2 половинки" in mold_type:
                        st.info("Выполняется разрез формы ровно пополам...")
                        
                        # Создаем гигантские кубы для отсечения левой и правой части
                        max_dim = height + radius * 2 + 50
                        
                        right_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        right_box.apply_translation([max_dim/2.0, 0, 0])
                        
                        left_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        left_box.apply_translation([-max_dim/2.0, 0, 0])
                        
                        # Пересекаем молд с левым и правым кубом
                        part_right = trimesh.boolean.intersection([final_mold, right_box], engine='manifold')
                        part_left = trimesh.boolean.intersection([final_mold, left_box], engine='manifold')
                        
                        st.success("✅ Молд успешно разрезан на 2 половинки!")
                        
                        # Запаковываем обе половинки в один ZIP-архив
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                            zip_file.writestr("mold_left_side.stl", part_left.export(file_type='stl'))
                            zip_file.writestr("mold_right_side.stl", part_right.export(file_type='stl'))
                        
                        st.download_button(
                            label="Скачать половинки (ZIP-архив)",
                            data=zip_buffer.getvalue(),
                            file_name="mold_2_parts.zip",
                            mime="application/zip"
                        )
                    else:
                        st.success("✅ Цельный цилиндрический молд успешно создан!")
                        
                        final_data = final_mold.export(file_type='stl')
                        st.download_button(
                            label="Скачать цельный молд (STL)",
                            data=final_data,
                            file_name="mold_solid.stl",
                            mime="model/stl"
                        )

                except Exception as e:
                    st.error(f"Произошла ошибка при вычислениях: {e}")
                
                finally:
                    if os.path.exists(tmp_file_path):
                        os.remove(tmp_file_path)
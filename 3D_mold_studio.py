import streamlit as st
import trimesh
import tempfile
import os
import zipfile
import io

st.set_page_config(page_title="Генератор молдов", layout="wide")
st.title("🧱 Генератор силиконовых форм (Молдов)")

st.caption("Версия 3.0 (Экономная оболочка с ушками) | Обновлено: 23 августа 2026 г.")
st.markdown("---")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Настройки формы")
    uploaded_file = st.file_uploader("Загрузите мастер-модель", type=["stl", "3mf"])
    
    st.markdown("---")
    mold_type = st.radio(
        "Конструкция молда:",
        ["Разрезать на 2 половинки (готово под струбцины)", 
         "Цельная оболочка (для самостоятельной резки в слайсере)"]
    )
    st.markdown("---")
    
    scale_option = st.radio(
        "Масштаб",
        [1.0, 10.0, 25.4],
        format_func=lambda x: "Без изменений (x1)" if x == 1.0 else ("Из Сантиметров (x10)" if x == 10.0 else "Из Дюймов (x25.4)")
    )
    st.markdown("---")
    
    wall_thickness = st.slider("Толщина стенок оболочки (мм)", min_value=2, max_value=15, value=6, step=1)
    bottom_offset = st.slider("Толщина дна молда (мм)", min_value=1, max_value=10, value=3, step=1)
    sprue_diam = st.slider("Диаметр литника (мм)", min_value=0, max_value=20, value=8, step=1)

with col2:
    st.subheader("Обработка и результат")
    
    if uploaded_file is not None:
        if st.button("Сгенерировать молд", type="primary"):
            with st.spinner("Создание анатомической оболочки..."):
                
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
                    
                    # 1. Центрируем мастер-модель
                    bounds_center = (mesh.bounds[0] + mesh.bounds[1]) / 2.0
                    mesh.apply_translation(-bounds_center)
                    
                    raccoon_z_min = -extents[2]/2.0
                    raccoon_z_max = extents[2]/2.0
                    mold_z_min = raccoon_z_min - bottom_offset
                    
                    # 2. Создаем "ком глины" (Convex Hull - выпуклая оболочка)
                    blob_mold = mesh.convex_hull
                    
                    # 3. Растягиваем оболочку на толщину стенок
                    sx = (extents[0] + wall_thickness * 2) / extents[0]
                    sy = (extents[1] + wall_thickness * 2) / extents[1]
                    sz = (extents[2] + wall_thickness * 2 + bottom_offset) / extents[2]
                    blob_mold.apply_scale([sx, sy, sz])
                    
                    # 4. Срезаем низ, чтобы форма ровно стояла на столе
                    max_dim = max(extents) * 3
                    cut_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                    cut_box.apply_translation([0, 0, mold_z_min + max_dim/2.0])
                    mold_base = trimesh.boolean.intersection([blob_mold, cut_box], engine='manifold')
                    
                    # 5. Добавляем ушки для струбцин (с плоским дном)
                    m_bounds = mold_base.bounds
                    m_length = m_bounds[1][1] - m_bounds[0][1]
                    
                    ear_w = 15.0 # Ширина ушка 15 мм
                    ear_h = max(10.0, (m_bounds[1][2] - m_bounds[0][2]) * 0.4) # Высота ушка
                    ear_l = max(15.0, m_length * 0.5) # Длина ушка
                    
                    # Правое ушко
                    ear_right = trimesh.creation.box(extents=[ear_w, ear_l, ear_h])
                    ear_right.apply_translation([m_bounds[1][0] + ear_w/2.0 - 2.0, 0, mold_z_min + ear_h/2.0])
                    
                    # Левое ушко
                    ear_left = trimesh.creation.box(extents=[ear_w, ear_l, ear_h])
                    ear_left.apply_translation([m_bounds[0][0] - ear_w/2.0 + 2.0, 0, mold_z_min + ear_h/2.0])
                    
                    mold_with_ears = trimesh.boolean.union([mold_base, ear_right, ear_left], engine='manifold')
                    
                    # 6. Литник
                    if sprue_diam > 0:
                        sprue = trimesh.creation.cylinder(radius=sprue_diam/2.0, height=extents[2] + 40)
                        sprue.apply_translation([0, 0, raccoon_z_max + 20])
                        mesh_to_subtract = trimesh.boolean.union([mesh, sprue], engine='manifold')
                    else:
                        mesh_to_subtract = mesh
                        
                    mesh_to_subtract.apply_translation([0, 0, 0.05])
                    
                    # 7. Финальное вычитание
                    final_mold = trimesh.boolean.difference([mold_with_ears, mesh_to_subtract], engine='manifold')
                    
                    # 8. Логика выдачи результата
                    if "Разрезать" in mold_type:
                        st.info("Выполняется разрез оболочки ровно пополам...")
                        
                        right_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        right_box.apply_translation([max_dim/2.0, 0, 0])
                        
                        left_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        left_box.apply_translation([-max_dim/2.0, 0, 0])
                        
                        part_right = trimesh.boolean.intersection([final_mold, right_box], engine='manifold')
                        part_left = trimesh.boolean.intersection([final_mold, left_box], engine='manifold')
                        
                        st.success("✅ Скорлупа успешно разрезана на 2 половинки!")
                        
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                            zip_file.writestr("mold_shell_left.stl", part_left.export(file_type='stl'))
                            zip_file.writestr("mold_shell_right.stl", part_right.export(file_type='stl'))
                        
                        st.download_button(
                            label="Скачать половинки (ZIP-архив)",
                            data=zip_buffer.getvalue(),
                            file_name="mold_shell_2_parts.zip",
                            mime="application/zip"
                        )
                    else:
                        st.success("✅ Цельная скорлупа успешно создана!")
                        
                        final_data = final_mold.export(file_type='stl')
                        st.download_button(
                            label="Скачать цельный молд (STL)",
                            data=final_data,
                            file_name="mold_shell_solid.stl",
                            mime="model/stl"
                        )

                except Exception as e:
                    st.error(f"Произошла ошибка при вычислениях: {e}")
                
                finally:
                    if os.path.exists(tmp_file_path):
                        os.remove(tmp_file_path)
import streamlit as st
import trimesh
import tempfile
import os
import zipfile
import io

st.set_page_config(page_title="Генератор молдов", layout="wide")
st.title("🧱 Генератор силиконовых форм (Молдов)")

st.caption("Версия 5.0 (Умный литник + Блоки по швам) | Обновлено: 23 августа 2026 г.")
st.markdown("---")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Настройки формы")
    uploaded_file = st.file_uploader("Загрузите мастер-модель", type=["stl", "3mf"])
    
    st.markdown("---")
    mold_type = st.radio(
        "Конструкция молда:",
        ["Разрезать на 2 половинки (готово под струбцины)", 
         "Цельная оболочка (для самостоятельной резки)"]
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
            with st.spinner("Анализ высот и расстановка креплений..."):
                
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
                    
                    # 1. Центрируем мастер-модель строго в ноль
                    bounds_center = (mesh.bounds[0] + mesh.bounds[1]) / 2.0
                    mesh.apply_translation(-bounds_center)
                    
                    raccoon_z_min = -extents[2]/2.0
                    mold_z_min = raccoon_z_min - bottom_offset
                    
                    # 2. Создаем "ком глины" (Convex Hull)
                    blob_mold = mesh.convex_hull
                    
                    # 3. Масштабируем скорлупу
                    blob_center = (blob_mold.bounds[0] + blob_mold.bounds[1]) / 2.0
                    blob_mold.apply_translation(-blob_center) 
                    
                    sx = (blob_mold.extents[0] + wall_thickness * 2.0 + 2.0) / blob_mold.extents[0]
                    sy = (blob_mold.extents[1] + wall_thickness * 2.0 + 2.0) / blob_mold.extents[1]
                    sz = (blob_mold.extents[2] + wall_thickness * 2.0 + bottom_offset + 2.0) / blob_mold.extents[2]
                    blob_mold.apply_scale([sx, sy, sz])
                    
                    blob_mold.apply_translation(blob_center)
                    
                    # 4. Срезаем низ для ровного дна
                    max_dim = max(extents) * 3
                    cut_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                    cut_box.apply_translation([0, 0, mold_z_min + max_dim/2.0])
                    mold_base = trimesh.boolean.intersection([blob_mold, cut_box], engine='manifold')
                    
                    # 5. КУБИКИ ДЛЯ СТРУБЦИН (Строго вдоль шва X=0)
                    m_bounds = mold_base.bounds
                    m_y_min, m_y_max = m_bounds[0][1], m_bounds[1][1]
                    m_z_min, m_z_max = m_bounds[0][2], m_bounds[1][2]
                    
                    block_w = 30.0 # Ширина (по 15 мм на каждую половину)
                    block_l = 25.0 # Длина (глубоко врезаем в форму)
                    block_h = 20.0 # Высота
                    
                    blocks = []
                    
                    # Распределяем по высоте: 25% и 75%
                    z_low = m_z_min + (m_z_max - m_z_min) * 0.25
                    z_high = m_z_min + (m_z_max - m_z_min) * 0.75
                    
                    # Блоки спереди (торчат вперед)
                    b1 = trimesh.creation.box(extents=[block_w, block_l, block_h])
                    b1.apply_translation([0, m_y_max - 5.0, z_low])
                    blocks.append(b1)
                    
                    b2 = trimesh.creation.box(extents=[block_w, block_l, block_h])
                    b2.apply_translation([0, m_y_max - 5.0, z_high])
                    blocks.append(b2)
                    
                    # Блоки сзади (торчат назад)
                    b3 = trimesh.creation.box(extents=[block_w, block_l, block_h])
                    b3.apply_translation([0, m_y_min + 5.0, z_low])
                    blocks.append(b3)
                    
                    b4 = trimesh.creation.box(extents=[block_w, block_l, block_h])
                    b4.apply_translation([0, m_y_min + 5.0, z_high])
                    blocks.append(b4)
                    
                    # Впаиваем блоки в скорлупу
                    mold_with_ears = trimesh.boolean.union([mold_base] + blocks, engine='manifold')
                    
                    # 6. УМНЫЙ ЛИТНИК (В самой верхней точке)
                    if sprue_diam > 0:
                        # Ищем самую высокую вершину в модели (например, ухо)
                        highest_idx = mesh.vertices[:, 2].argmax()
                        highest_y = mesh.vertices[highest_idx, 1]
                        highest_z = mesh.vertices[highest_idx, 2]
                        
                        # Создаем длинный литник и ставим на ось шва (X=0) над самой высокой точкой
                        sprue = trimesh.creation.cylinder(radius=sprue_diam/2.0, height=extents[2] + 40)
                        sprue.apply_translation([0, highest_y, highest_z + 20])
                        
                        mesh_to_subtract = trimesh.boolean.union([mesh, sprue], engine='manifold')
                    else:
                        mesh_to_subtract = mesh
                        
                    mesh_to_subtract.apply_translation([0, 0, 0.05])
                    
                    # 7. Финальное вычитание
                    final_mold = trimesh.boolean.difference([mold_with_ears, mesh_to_subtract], engine='manifold')
                    
                    # 8. Логика выдачи
                    if "Разрезать" in mold_type:
                        st.info("Выполняется разрез оболочки ровно пополам...")
                        
                        right_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        right_box.apply_translation([max_dim/2.0, 0, 0])
                        
                        left_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        left_box.apply_translation([-max_dim/2.0, 0, 0])
                        
                        part_right = trimesh.boolean.intersection([final_mold, right_box], engine='manifold')
                        part_left = trimesh.boolean.intersection([final_mold, left_box], engine='manifold')
                        
                        st.success("✅ Скорлупа успешно разрезана на 2 половинки с креплениями!")
                        
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
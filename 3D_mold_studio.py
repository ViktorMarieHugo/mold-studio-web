import streamlit as st
import trimesh
import tempfile
import os
import zipfile
import io

st.set_page_config(page_title="Генератор молдов", layout="wide")
st.title("🧱 Генератор силиконовых форм (Молдов)")

st.caption("Версия 6.0 (Сплошные рельсы + Замки + Выбор литника) | Обновлено: 23 августа 2026 г.")
st.markdown("---")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Настройки формы")
    uploaded_file = st.file_uploader("Загрузите мастер-модель", type=["stl", "3mf"])
    
    st.markdown("---")
    mold_type = st.radio(
        "Конструкция молда:",
        ["Разрезать на 2 половинки (с готовыми замками и фланцами)", 
         "Цельная оболочка (для самостоятельной резки)"]
    )
    st.markdown("---")
    
    sprue_mode = st.radio(
        "Отверстия для заливки:",
        ["Без отверстий (сделаю сам в Bambu Studio над каждой деталью)", 
         "Автоматически (один канал в самой высокой точке)"]
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
            with st.spinner("Создание профессиональной формы с замками..."):
                
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
                    
                    # 5. СПЛОШНЫЕ РЕЛЬСЫ (Фланцы) от низа до верха
                    m_bounds = mold_base.bounds
                    m_y_min, m_y_max = m_bounds[0][1], m_bounds[1][1]
                    m_z_min, m_z_max = m_bounds[0][2], m_bounds[1][2]
                    
                    mold_h = m_z_max - m_z_min
                    mold_center_z = (m_z_max + m_z_min) / 2.0
                    
                    block_w = 30.0 # Ширина фланца
                    block_l = 20.0 # Врезание в молд
                    
                    # Рельса спереди
                    flange_front = trimesh.creation.box(extents=[block_w, block_l, mold_h])
                    flange_front.apply_translation([0, m_y_max - 2.0, mold_center_z])
                    
                    # Рельса сзади
                    flange_back = trimesh.creation.box(extents=[block_w, block_l, mold_h])
                    flange_back.apply_translation([0, m_y_min + 2.0, mold_center_z])
                    
                    mold_with_ears = trimesh.boolean.union([mold_base, flange_front, flange_back], engine='manifold')
                    
                    # 6. ЛИТНИК (Умный или ручной)
                    if "Автоматически" in sprue_mode and sprue_diam > 0:
                        highest_idx = mesh.vertices[:, 2].argmax()
                        highest_y = mesh.vertices[highest_idx, 1]
                        highest_z = mesh.vertices[highest_idx, 2]
                        
                        sprue = trimesh.creation.cylinder(radius=sprue_diam/2.0, height=extents[2] + 40)
                        sprue.apply_translation([0, highest_y, highest_z + 20])
                        mesh_to_subtract = trimesh.boolean.union([mesh, sprue], engine='manifold')
                    else:
                        mesh_to_subtract = mesh
                        
                    mesh_to_subtract.apply_translation([0, 0, 0.05])
                    
                    # 7. Финальное вычитание (получаем полость)
                    final_mold = trimesh.boolean.difference([mold_with_ears, mesh_to_subtract], engine='manifold')
                    
                    # 8. Логика выдачи и СОЗДАНИЕ ЗАМКОВ
                    if "Разрезать" in mold_type:
                        st.info("Разрезаем и генерируем сферические замки...")
                        
                        right_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        right_box.apply_translation([max_dim/2.0, 0, 0])
                        
                        left_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        left_box.apply_translation([-max_dim/2.0, 0, 0])
                        
                        part_right_base = trimesh.boolean.intersection([final_mold, right_box], engine='manifold')
                        part_left_base = trimesh.boolean.intersection([final_mold, left_box], engine='manifold')
                        
                        # Генерируем замки (сферы)
                        locks_male = []   # Выпуклые (радиус 3.3 мм)
                        locks_female = [] # Впалые (радиус 3.5 мм - зазор 0.2 мм для идеальной печати)
                        
                        z_low = m_z_min + mold_h * 0.25
                        z_high = m_z_min + mold_h * 0.75
                        
                        for z_pos in [z_low, z_high]:
                            y_f = m_y_max - 2.0
                            locks_male.append(trimesh.creation.icosphere(radius=3.3, subdivisions=3).apply_translation([0, y_f, z_pos]))
                            locks_female.append(trimesh.creation.icosphere(radius=3.5, subdivisions=3).apply_translation([0, y_f, z_pos]))
                            
                            y_b = m_y_min + 2.0
                            locks_male.append(trimesh.creation.icosphere(radius=3.3, subdivisions=3).apply_translation([0, y_b, z_pos]))
                            locks_female.append(trimesh.creation.icosphere(radius=3.5, subdivisions=3).apply_translation([0, y_b, z_pos]))
                            
                        mesh_locks_male = trimesh.util.concatenate(locks_male)
                        mesh_locks_female = trimesh.util.concatenate(locks_female)
                        
                        # Впаиваем выпуклости в правую половину, вырезаем ямки из левой
                        part_right = trimesh.boolean.union([part_right_base, mesh_locks_male], engine='manifold')
                        part_left = trimesh.boolean.difference([part_left_base, mesh_locks_female], engine='manifold')
                        
                        st.success("✅ Молд разрезан! Сферические замки с зазором под 3D-печать созданы.")
                        
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                            zip_file.writestr("mold_left_female.stl", part_left.export(file_type='stl'))
                            zip_file.writestr("mold_right_male.stl", part_right.export(file_type='stl'))
                        
                        st.download_button(
                            label="Скачать половинки (ZIP-архив)",
                            data=zip_buffer.getvalue(),
                            file_name="mold_professional.zip",
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
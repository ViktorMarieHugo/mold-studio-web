import streamlit as st
import trimesh
import tempfile
import os
import zipfile
import io
import math

st.set_page_config(page_title="Генератор молдов", layout="wide")
st.title("🧱 Генератор форм для заливки силикона")

st.caption("Версия: Чистый силикон (Опалубка + Мастер-модель) | Без лишних функций")
st.markdown("---")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Настройки формы")
    uploaded_file = st.file_uploader("Загрузите мастер-модель", type=["stl", "3mf"])
    
    st.markdown("---")
    st.info("💡 **Как это работает:** Модель перевернется вверх ногами. Сверху добавится планка-держатель (это ваш пуансон). Вокруг сгенерируется пластиковый горшок из двух половин. Зазор между ними — это ваш будущий силиконовый молд.")
    
    silicone_thickness = st.slider("Толщина силиконовой формы (Зазор, мм)", min_value=5, max_value=30, value=10, step=1)
    plastic_wall = st.slider("Толщина пластиковой опалубки (мм)", min_value=2, max_value=10, value=3, step=1)

with col2:
    st.subheader("Обработка и результат")
    
    if uploaded_file is not None:
        
        final_filename = "silicone_mold_kit.zip"
        
        if st.button("Сгенерировать комплект", type="primary"):
            with st.spinner("Генерация пуансона и пластиковой опалубки..."):
                
                file_extension = os.path.splitext(uploaded_file.name)[1].lower()
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_file_path = tmp_file.name
                
                try:
                    loaded_data = trimesh.load(tmp_file_path)
                    mesh = loaded_data.dump(concatenate=True) if isinstance(loaded_data, trimesh.Scene) else loaded_data
                    
                    # 1. ПЕРЕВОРОТ И ЦЕНТРИРОВАНИЕ (База модели становится нулем Z=0)
                    mesh.apply_translation(-mesh.centroid)
                    rot_matrix = trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0])
                    mesh.apply_transform(rot_matrix)
                    
                    # Ровняем самую верхнюю плоскую часть (базу зайца) строго по Z=0
                    mesh.apply_translation([0, 0, -mesh.bounds[1][2]])
                    b_c = (mesh.bounds[0] + mesh.bounds[1]) / 2.0
                    mesh.apply_translation([-b_c[0], -b_c[1], 0])
                    
                    # 2. ГЕНЕРАЦИЯ ПУАНСОНА (Заяц + Планка)
                    plank_w = mesh.extents[0] + (silicone_thickness * 2) + (plastic_wall * 2) + 30.0
                    plank_d = 20.0
                    plank_h = 10.0
                    plank = trimesh.creation.box(extents=[plank_w, plank_d, plank_h])
                    plank.apply_translation([0, 0, plank_h / 2.0]) # Планка лежит ровно на Z=0 и растет вверх
                    
                    puanson = trimesh.boolean.union([mesh, plank], engine='manifold')
                    
                    # 3. ВНУТРЕННИЙ ОБЪЕМ (Форма самого силикона)
                    hull = mesh.convex_hull
                    hull_c = (hull.bounds[0] + hull.bounds[1]) / 2.0
                    hull.apply_translation(-hull_c)
                    
                    sx = (hull.extents[0] + silicone_thickness * 2) / hull.extents[0]
                    sy = (hull.extents[1] + silicone_thickness * 2) / hull.extents[1]
                    sz = (hull.extents[2] + silicone_thickness * 2) / hull.extents[2]
                    hull.apply_scale([sx, sy, sz])
                    hull.apply_translation(hull_c)
                    
                    giant_dim = max(mesh.extents) * 3.0
                    z_top = 0.0 # Верх горшка упирается в планку
                    z_bot_silicone = mesh.bounds[0][2] - silicone_thickness # Плоское дно силикона (будущая верхушка молда)
                    
                    inner_cut = trimesh.creation.box(extents=[giant_dim, giant_dim, z_top - z_bot_silicone])
                    inner_cut.apply_translation([0, 0, z_bot_silicone + (z_top - z_bot_silicone)/2.0])
                    inner_vol = trimesh.boolean.intersection([hull, inner_cut], engine='manifold')
                    
                    # 4. ВНЕШНИЙ ОБЪЕМ (Пластиковый горшок)
                    outer_hull = mesh.convex_hull
                    outer_hull.apply_translation(-hull_c)
                    
                    sx_o = (outer_hull.extents[0] + (silicone_thickness + plastic_wall) * 2) / outer_hull.extents[0]
                    sy_o = (outer_hull.extents[1] + (silicone_thickness + plastic_wall) * 2) / outer_hull.extents[1]
                    sz_o = (outer_hull.extents[2] + (silicone_thickness + plastic_wall) * 2) / outer_hull.extents[2]
                    outer_hull.apply_scale([sx_o, sy_o, sz_o])
                    outer_hull.apply_translation(hull_c)
                    
                    z_bot_plastic = z_bot_silicone - plastic_wall # Пластиковое дно опалубки
                    outer_cut = trimesh.creation.box(extents=[giant_dim, giant_dim, z_top - z_bot_plastic])
                    outer_cut.apply_translation([0, 0, z_bot_plastic + (z_top - z_bot_plastic)/2.0])
                    outer_vol = trimesh.boolean.intersection([outer_hull, outer_cut], engine='manifold')
                    
                    # Вырезаем полость в горшке
                    pot_raw = trimesh.boolean.difference([outer_vol, inner_vol], engine='manifold')
                    
                    # Добавляем рельсы для замков
                    flange_profile = outer_vol.copy()
                    fc = (flange_profile.bounds[0] + flange_profile.bounds[1]) / 2.0
                    flange_profile.apply_translation(-fc)
                    flange_profile.apply_scale([1.0, 1.2, 1.0])
                    flange_profile.apply_translation(fc)
                    
                    slab = trimesh.creation.box(extents=[20.0, giant_dim, giant_dim])
                    flange = trimesh.boolean.intersection([flange_profile, slab], engine='manifold')
                    pot = trimesh.boolean.union([pot_raw, flange], engine='manifold')
                    
                    # 5. РАЗРЕЗ ГОРШКА И ЗАМКИ
                    right_box = trimesh.creation.box(extents=[giant_dim, giant_dim, giant_dim])
                    right_box.apply_translation([giant_dim/2.0, 0, 0])
                    left_box = trimesh.creation.box(extents=[giant_dim, giant_dim, giant_dim])
                        left_box.apply_translation([-giant_dim/2.0, 0, 0])
                    
                    part_right_base = trimesh.boolean.intersection([pot, right_box], engine='manifold')
                    part_left_base = trimesh.boolean.intersection([pot, left_box], engine='manifold')
                    
                    locks_male, locks_female = [], []
                    z_low = z_bot_plastic + (z_top - z_bot_plastic) * 0.3
                    z_high = z_bot_plastic + (z_top - z_bot_plastic) * 0.7
                    
                    for z_pos in [z_low, z_high]:
                        slice_2d = pot.section(plane_origin=[0,0,z_pos], plane_normal=[0,0,1])
                        if slice_2d is not None:
                            y_min = slice_2d.bounds[0][1]
                            y_max = slice_2d.bounds[1][1]
                            for pos in [[0, y_min + 6.0, z_pos], [0, y_max - 6.0, z_pos]]:
                                locks_male.append(trimesh.creation.icosphere(radius=3.0, subdivisions=3).apply_translation(pos))
                                locks_female.append(trimesh.creation.icosphere(radius=3.2, subdivisions=3).apply_translation(pos))
                    
                    if locks_male:
                        part_right = trimesh.boolean.union([part_right_base, trimesh.util.concatenate(locks_male)], engine='manifold')
                        part_left = trimesh.boolean.difference([part_left_base, trimesh.util.concatenate(locks_female)], engine='manifold')
                    else:
                        part_right, part_left = part_right_base, part_left_base
                    
                    # 6. УПАКОВКА В ZIP
                    zip_buffer = io.BytesIO()
                    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                        zip_file.writestr("1_puanson_master.stl", puanson.export(file_type='stl'))
                        zip_file.writestr("2_pot_left.stl", part_left.export(file_type='stl'))
                        zip_file.writestr("3_pot_right.stl", part_right.export(file_type='stl'))
                    
                    st.success("✅ Готово! Сгенерированы мастер-пуансон и 2 половинки пластиковой опалубки.")
                    st.download_button("Скачать комплект (ZIP-архив)", data=zip_buffer.getvalue(), file_name=final_filename, mime="application/zip")
                    
                except Exception as e:
                    st.error(f"Произошла ошибка: {e}")
                finally:
                    if os.path.exists(tmp_file_path): os.remove(tmp_file_path)
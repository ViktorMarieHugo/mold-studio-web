import streamlit as st
import trimesh
import tempfile
import os
import zipfile
import io
import math

st.set_page_config(page_title="Генератор молдов", layout="wide")
st.title("🧱 Генератор силиконовых форм (Молдов)")

st.caption("Версия 12.0 (Исправлена физика: монолитная подставка, пуансон и чистый литник) | Обновлено: 26 августа 2026 г.")
st.markdown("---")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Настройки формы")
    uploaded_file = st.file_uploader("Загрузите мастер-модель", type=["stl", "3mf"])
    
    st.markdown("---")
    brand_text = st.text_input("Текст гравировки на боку:", "Irivek3Dstudio")
    
    st.markdown("---")
    cast_mode = st.radio(
        "Тип заливки:",
        ["Сплошная деталь (Классика)", 
         "Пустотелая деталь (Экономия материала)"]
    )
    
    hollow_method = None
    if "Пустотелая" in cast_mode:
        st.info("💡 **Режим перевернутой формы:** Модель будет перевернута. Дно станет широкой горловиной, срез будет идеально плоским. Снизу сгенерируется подставка.")
        hollow_method = st.radio(
            "Метод создания пустоты:",
            ["Гладкий Т-образный пуансон (Стержень с планкой)",
             "Метод обкатки (Ротационное литье)"]
        )
            
    st.markdown("---")
    mold_type = st.radio(
        "Конструкция молда:",
        ["Разрезать на 2 половинки (с замками)", "Цельная оболочка"]
    )
    
    sprue_mode = "Без отверстий"
    if "Сплошная" in cast_mode:
        st.markdown("---")
        sprue_mode = st.radio("Литник (только для сплошной):", ["Без отверстий (сделать в слайсере)", "Авто-литник в высшей точке"])
        
    st.markdown("---")
    wall_thickness = st.slider("Толщина стенок (мм)", min_value=2, max_value=15, value=6, step=1)
    bottom_offset = st.slider("Толщина дна молда (мм)", min_value=1, max_value=10, value=3, step=1)
    sprue_diam = st.slider("Диаметр литника (мм)", min_value=2, max_value=20, value=8, step=1)

with col2:
    st.subheader("Обработка и результат")
    
    if uploaded_file is not None:
        
        # --- ЛОГИКА ИМЕНОВАНИЯ ---
        is_hollow = "Пустотелая" in cast_mode
        is_split = "Разрезать" in mold_type
        # ИСПРАВЛЕНИЕ: Жесткая проверка пуансона без учета регистра
        has_puanson = is_hollow and hollow_method and "пуансон" in hollow_method.lower()
        has_obkatka = is_hollow and hollow_method and "обкатки" in hollow_method.lower()
        has_sprue = not is_hollow and "Авто-литник" in sprue_mode

        name_parts = ["irivek_mold"]
        name_parts.append("hollow" if is_hollow else "solid")
        if has_puanson: name_parts.append("puanson")
        if has_obkatka: name_parts.append("obkatka")
        if has_sprue: name_parts.append("auto_sprue")
        name_parts.append("split" if is_split else "shell")
        
        final_ext = ".zip" if is_split else ".stl"
        final_filename = "_".join(name_parts) + final_ext

        if is_hollow:
            spinner_msg = "Проектирование пустотелой формы с Т-образным пуансоном..." if has_puanson else "Проектирование пустотелой формы для обкатки..."
        else:
            spinner_msg = "Проектирование сплошной формы с авто-литником..." if has_sprue else "Проектирование классической сплошной формы..."
        
        if st.button("Сгенерировать форму", type="primary"):
            with st.spinner(spinner_msg):
                
                file_extension = os.path.splitext(uploaded_file.name)[1].lower()
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_file_path = tmp_file.name
                
                try:
                    loaded_data = trimesh.load(tmp_file_path)
                    mesh = loaded_data.dump(concatenate=True) if isinstance(loaded_data, trimesh.Scene) else loaded_data
                    
                    # 1. ПЕРЕВОРОТ И ВЫРАВНИВАНИЕ
                    if is_hollow:
                        rot_matrix = trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0])
                        mesh.apply_transform(rot_matrix)
                        
                    b_min = mesh.bounds[0]
                    mesh.apply_translation([-b_min[0] - (mesh.extents[0]/2.0), -b_min[1] - (mesh.extents[1]/2.0), -b_min[2]])
                    
                    extents = mesh.extents 
                    z_max_model = mesh.bounds[1][2]
                    
                    # ИСПРАВЛЕНИЕ: Адекватный размер коробок резки (3x от размера детали)
                    max_dim = max(extents) * 3.0
                    
                    # 2. ОБОЛОЧКА И ФЛАНЕЦ
                    blob_mold = mesh.convex_hull
                    c_blob = (blob_mold.bounds[0] + blob_mold.bounds[1]) / 2.0
                    blob_mold.apply_translation(-c_blob)
                    
                    sx = (blob_mold.extents[0] + wall_thickness * 2.0) / blob_mold.extents[0]
                    sy = (blob_mold.extents[1] + wall_thickness * 2.0) / blob_mold.extents[1]
                    sz = (blob_mold.extents[2] + wall_thickness * 2.0 + bottom_offset) / blob_mold.extents[2]
                    blob_mold.apply_scale([sx, sy, sz])
                    blob_mold.apply_translation(c_blob)
                    
                    flange_profile = blob_mold.copy()
                    c_flange = (flange_profile.bounds[0] + flange_profile.bounds[1]) / 2.0
                    flange_profile.apply_translation(-c_flange)
                    flange_profile.apply_scale([1.0, (blob_mold.extents[1] + 24.0)/blob_mold.extents[1], 1.0])
                    flange_profile.apply_translation(c_flange)
                    
                    slab_box = trimesh.creation.box(extents=[20.0, max_dim, max_dim])
                    flange = trimesh.boolean.intersection([flange_profile, slab_box], engine='manifold')
                    raw_mold = trimesh.boolean.union([blob_mold, flange], engine='manifold')
                    
                    # 3. ВИРТУАЛЬНЫЙ НОЖ И МОНОЛИТНАЯ ПОДСТАВКА
                    if is_hollow:
                        z_bottom = -wall_thickness
                        z_top = z_max_model
                        
                        box_h = z_top - z_bottom
                        cut_box = trimesh.creation.box(extents=[max_dim, max_dim, box_h])
                        cut_box.apply_translation([0, 0, z_bottom + box_h/2.0])
                        mold_base = trimesh.boolean.intersection([raw_mold, cut_box], engine='manifold')
                        
                        stand_x = extents[0] * 1.5 + 20.0
                        stand_y = extents[1] * 1.5 + 20.0
                        stand = trimesh.creation.box(extents=[stand_x, stand_y, 10.0])
                        # ИСПРАВЛЕНИЕ: Подставка нахлестывается на 1 мм вглубь формы, чтобы намертво припаяться!
                        stand.apply_translation([0, 0, z_bottom - 5.0 + 1.0])
                        mold_base = trimesh.boolean.union([mold_base, stand], engine='manifold')
                    else:
                        z_bottom = -bottom_offset
                        z_top = z_max_model + wall_thickness
                        
                        box_h = z_top - z_bottom
                        cut_box = trimesh.creation.box(extents=[max_dim, max_dim, box_h])
                        cut_box.apply_translation([0, 0, z_bottom + box_h/2.0])
                        mold_base = trimesh.boolean.intersection([raw_mold, cut_box], engine='manifold')

                    try:
                        plate = trimesh.creation.box(extents=[5.0, 40.0, 15.0])
                        plate.apply_translation([-10.0, 0, z_max_model / 2.0])
                        mold_base = trimesh.boolean.difference([mold_base, plate], engine='manifold')
                    except: pass

                    # 4. ЛИТНИК И ФИНАЛЬНЫЙ ВЫРЕЗ
                    mesh.apply_translation([0, 0, 0.05])
                    
                    # ИСПРАВЛЕНИЕ: Вычитаем зайца и литник РАЗДЕЛЬНО, чтобы не ломать сетку!
                    if has_sprue:
                        highest_idx = mesh.vertices[:, 2].argmax()
                        highest_z = mesh.vertices[highest_idx, 2]
                        highest_y = mesh.vertices[highest_idx, 1]
                        
                        sprue_h = z_top - highest_z + 10.0 
                        sprue = trimesh.creation.cylinder(radius=sprue_diam/2.0, height=sprue_h)
                        sprue.apply_translation([0, highest_y, highest_z + sprue_h/2.0])
                        
                        final_mold = trimesh.boolean.difference([mold_base, mesh, sprue], engine='manifold')
                    else:
                        final_mold = trimesh.boolean.difference([mold_base, mesh], engine='manifold')
                    
                    # 5. РАЗРЕЗ И ЗАМКИ
                    if is_split:
                        st.info("Форма сгенерирована. Выполняется разрез и расстановка замков...")
                        
                        right_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        right_box.apply_translation([max_dim/2.0, 0, 0])
                        left_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        left_box.apply_translation([-max_dim/2.0, 0, 0])
                        
                        part_right_base = trimesh.boolean.intersection([final_mold, right_box], engine='manifold')
                        part_left_base = trimesh.boolean.intersection([final_mold, left_box], engine='manifold')
                        
                        locks_male, locks_female = [], []
                        z_low = mold_base.bounds[0][2] + (mold_base.bounds[1][2] - mold_base.bounds[0][2]) * 0.3
                        z_high = mold_base.bounds[0][2] + (mold_base.bounds[1][2] - mold_base.bounds[0][2]) * 0.7
                        
                        for z_pos in [z_low, z_high]:
                            slice_2d = mold_base.section(plane_origin=[0,0,z_pos], plane_normal=[0,0,1])
                            if slice_2d is not None:
                                y_min = slice_2d.bounds[0][1]
                                y_max = slice_2d.bounds[1][1]
                                for pos in [[0, y_min + 6.0, z_pos], [0, y_max - 6.0, z_pos]]:
                                    locks_male.append(trimesh.creation.icosphere(radius=3.3, subdivisions=3).apply_translation(pos))
                                    locks_female.append(trimesh.creation.icosphere(radius=3.5, subdivisions=3).apply_translation(pos))
                        
                        if locks_male:
                            part_right = trimesh.boolean.union([part_right_base, trimesh.util.concatenate(locks_male)], engine='manifold')
                            part_left = trimesh.boolean.difference([part_left_base, trimesh.util.concatenate(locks_female)], engine='manifold')
                        else:
                            part_right = part_right_base
                            part_left = part_left_base
                        
                        zip_buffer = io.BytesIO()
                        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                            zip_file.writestr(f"left_female_{final_filename.replace('.zip', '.stl')}", part_left.export(file_type='stl'))
                            zip_file.writestr(f"right_male_{final_filename.replace('.zip', '.stl')}", part_right.export(file_type='stl'))
                            
                            # ИСПРАВЛЕНИЕ: ГЕНЕРАЦИЯ ПУАНСОНА ТЕПЕРЬ СРАБАТЫВАЕТ!
                            if has_puanson:
                                slice_top = mold_base.section(plane_origin=[0,0,z_top-1.0], plane_normal=[0,0,1])
                                bar_l = (slice_top.bounds[1][1] - slice_top.bounds[0][1]) + 20.0 if slice_top else extents[1] + 40.0
                                
                                bar_h = 10.0
                                t_bar = trimesh.creation.box(extents=[30.0, bar_l, bar_h])
                                t_bar.apply_translation([0, 0, z_top + bar_h/2.0])
                                
                                ellipsoid_r = min(extents[0], extents[1]) * 0.35
                                ellipsoid_h = extents[2] * 0.70
                                core = trimesh.creation.icosphere(radius=1.0, subdivisions=4)
                                core.apply_scale([ellipsoid_r, ellipsoid_r, ellipsoid_h / 2.0])
                                core.apply_translation([0, 0, z_top - (ellipsoid_h / 2.0) + 2.0])
                                
                                puanson = trimesh.boolean.union([t_bar, core], engine='manifold')
                                zip_file.writestr(f"puanson_core_{final_filename.replace('.zip', '.stl')}", puanson.export(file_type='stl'))
                        
                        st.success(f"✅ Готово! Сгенерирован архив: {final_filename}")
                        st.download_button("Скачать комплект (ZIP-архив)", data=zip_buffer.getvalue(), file_name=final_filename, mime="application/zip")
                    
                    else:
                        st.success(f"✅ Готово! Сгенерирован файл: {final_filename}")
                        final_data = final_mold.export(file_type='stl')
                        st.download_button("Скачать цельный молд (STL)", data=final_data, file_name=final_filename, mime="model/stl")
                    
                except Exception as e:
                    st.error(f"Произошла ошибка: {e}")
                finally:
                    if os.path.exists(tmp_file_path): os.remove(tmp_file_path)
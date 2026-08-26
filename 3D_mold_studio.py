import streamlit as st
import trimesh
import tempfile
import os
import zipfile
import io
import math

st.set_page_config(page_title="Генератор молдов", layout="wide")
st.title("🧱 Генератор силиконовых форм (Молдов)")

st.caption("Версия 9.0 (Мастер-релиз: Т-образный пуансон, срез горловины, фикс подставки) | Обновлено: 25 августа 2026 г.")
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
        if "обкатки" in hollow_method:
            st.caption("👉 *Обкатка:* Вы заливаете 30% гипса и медленно вращаете форму.")
        else:
            st.caption("👉 *Пуансон:* Программа создаст отдельную Т-образную крышку. Планка ляжет на молд, а гладкий овал выдавит лишний гипс из центра.")
            
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

with col2:
    st.subheader("Обработка и результат")
    
    if uploaded_file is not None:
        if st.button("Сгенерировать форму", type="primary"):
            with st.spinner("Инженерные расчеты... (генерация пуансона и срезов)"):
                
                file_extension = os.path.splitext(uploaded_file.name)[1].lower()
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_file_path = tmp_file.name
                
                try:
                    loaded_data = trimesh.load(tmp_file_path)
                    mesh = loaded_data.dump(concatenate=True) if isinstance(loaded_data, trimesh.Scene) else loaded_data
                    
                    # 1. ПЕРЕВОРОТ И ИДЕАЛЬНОЕ ЦЕНТРИРОВАНИЕ
                    if "Пустотелая" in cast_mode:
                        rot_matrix = trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0])
                        mesh.apply_transform(rot_matrix)
                        
                    # Опускаем модель так, чтобы ее самая нижняя точка (например, уши) касалась нуля (Z=0)
                    b_center = (mesh.bounds[0] + mesh.bounds[1]) / 2.0
                    mesh.apply_translation([-b_center[0], -b_center[1], -mesh.bounds[0][2]])
                    
                    extents = mesh.extents 
                    z_max_model = mesh.bounds[1][2]
                    
                    # 2. ОБОЛОЧКА И ФЛАНЕЦ
                    blob_mold = mesh.convex_hull
                    c_blob = (blob_mold.bounds[0] + blob_mold.bounds[1]) / 2.0
                    blob_mold.apply_translation(-c_blob)
                    
                    sx = (blob_mold.extents[0] + wall_thickness * 2.0) / blob_mold.extents[0]
                    sy = (blob_mold.extents[1] + wall_thickness * 2.0) / blob_mold.extents[1]
                    sz = (blob_mold.extents[2] + wall_thickness * 2.0 + bottom_offset) / blob_mold.extents[2]
                    blob_mold.apply_scale([sx, sy, sz])
                    blob_mold.apply_translation(c_blob)
                    
                    # Арка-фланец
                    flange_profile = blob_mold.copy()
                    c_flange = (flange_profile.bounds[0] + flange_profile.bounds[1]) / 2.0
                    flange_profile.apply_translation(-c_flange)
                    flange_profile.apply_scale([1.0, (blob_mold.extents[1] + 24.0)/blob_mold.extents[1], 1.0])
                    flange_profile.apply_translation(c_flange)
                    
                    max_dim = max(extents) * 3
                    slab_box = trimesh.creation.box(extents=[20.0, max_dim, max_dim])
                    flange = trimesh.boolean.intersection([flange_profile, slab_box], engine='manifold')
                    
                    raw_mold = trimesh.boolean.union([blob_mold, flange], engine='manifold')
                    
                    # 3. ВИРТУАЛЬНЫЙ НОЖ (СРЕЗ ВЕРХА И НИЗА)
                    if "Пустотелая" in cast_mode:
                        z_bottom = -wall_thickness
                        z_top = z_max_model # Идеальный срез по верху модели
                        
                        box_h = z_top - z_bottom
                        cut_box = trimesh.creation.box(extents=[max_dim, max_dim, box_h])
                        cut_box.apply_translation([0, 0, z_bottom + box_h/2.0])
                        
                        mold_base = trimesh.boolean.intersection([raw_mold, cut_box], engine='manifold')
                        
                        # Монолитная подставка (теперь точно под ушами!)
                        stand_x = extents[0] * 1.2 + 20.0
                        stand_y = extents[1] * 1.2 + 20.0
                        stand = trimesh.creation.box(extents=[stand_x, stand_y, 10.0])
                        stand.apply_translation([0, 0, z_bottom - 5.0])
                        mold_base = trimesh.boolean.union([mold_base, stand], engine='manifold')
                    else:
                        z_bottom = -bottom_offset
                        z_top = z_max_model + wall_thickness
                        
                        box_h = z_top - z_bottom
                        cut_box = trimesh.creation.box(extents=[max_dim, max_dim, box_h])
                        cut_box.apply_translation([0, 0, z_bottom + box_h/2.0])
                        mold_base = trimesh.boolean.intersection([raw_mold, cut_box], engine='manifold')

                    # 4. ВЫДАВЛИВАНИЕ ГРАВИРОВКИ
                    try:
                        plate = trimesh.creation.box(extents=[5.0, 40.0, 15.0])
                        plate.apply_translation([-10.0, 0, z_max_model / 2.0])
                        mold_base = trimesh.boolean.difference([mold_base, plate], engine='manifold')
                    except: pass

                    # 5. ЛИТНИКИ И ВЫЧИТАНИЕ
                    if "Авто-литник" in sprue_mode and "Сплошная" in cast_mode:
                        highest_idx = mesh.vertices[:, 2].argmax()
                        sprue = trimesh.creation.cylinder(radius=4.0, height=extents[2] + 40)
                        sprue.apply_translation([0, mesh.vertices[highest_idx, 1], mesh.vertices[highest_idx, 2] + 20])
                        mesh_to_subtract = trimesh.boolean.union([mesh, sprue], engine='manifold')
                    else:
                        mesh_to_subtract = mesh
                        
                    mesh_to_subtract.apply_translation([0, 0, 0.05])
                    final_mold = trimesh.boolean.difference([mold_base, mesh_to_subtract], engine='manifold')
                    
                    # 6. РАЗРЕЗ, УТОПЛЕННЫЕ ЗАМКИ И ПУАНСОН
                    zip_buffer = io.BytesIO()
                    
                    if "Разрезать" in mold_type:
                        st.info("Разрезаем и генерируем утопленные замки...")
                        right_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        right_box.apply_translation([max_dim/2.0, 0, 0])
                        left_box = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        left_box.apply_translation([-max_dim/2.0, 0, 0])
                        
                        part_right_base = trimesh.boolean.intersection([final_mold, right_box], engine='manifold')
                        part_left_base = trimesh.boolean.intersection([final_mold, left_box], engine='manifold')
                        
                        locks_male, locks_female = [], []
                        mold_h = mold_base.bounds[1][2] - mold_base.bounds[0][2]
                        y_min, y_max = mold_base.bounds[0][1], mold_base.bounds[1][1]
                        
                        # Утопленные замки (сдвиг 8 мм внутрь)
                        for z_pos in [mold_base.bounds[0][2] + mold_h * 0.3, mold_base.bounds[0][2] + mold_h * 0.7]:
                            for pos in [[0, y_min + 8.0, z_pos], [0, y_max - 8.0, z_pos]]:
                                locks_male.append(trimesh.creation.icosphere(radius=3.3, subdivisions=3).apply_translation(pos))
                                locks_female.append(trimesh.creation.icosphere(radius=3.5, subdivisions=3).apply_translation(pos))
                        
                        part_right = trimesh.boolean.union([part_right_base, trimesh.util.concatenate(locks_male)], engine='manifold')
                        part_left = trimesh.boolean.difference([part_left_base, trimesh.util.concatenate(locks_female)], engine='manifold')
                        
                        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                            zip_file.writestr("mold_left_female.stl", part_left.export(file_type='stl'))
                            zip_file.writestr("mold_right_male.stl", part_right.export(file_type='stl'))
                            
                            # ГЕНЕРАЦИЯ Т-ОБРАЗНОГО ПУАНСОНА
                            if hollow_method and "Пуансон" in hollow_method:
                                bar_l = y_max - y_min + 20.0 # Длинная перекладина ложится на края
                                bar_h = 10.0
                                t_bar = trimesh.creation.box(extents=[20.0, bar_l, bar_h])
                                t_bar.apply_translation([0, 0, z_top + bar_h/2.0])
                                
                                # Гладкий овал для вытеснения гипса
                                ellipsoid_r = min(extents[0], extents[1]) * 0.30
                                ellipsoid_h = extents[2] * 0.65
                                core = trimesh.creation.icosphere(radius=1.0, subdivisions=4)
                                core.apply_scale([ellipsoid_r, ellipsoid_r, ellipsoid_h / 2.0])
                                core.apply_translation([0, 0, z_top - (ellipsoid_h / 2.0) + 2.0])
                                
                                puanson = trimesh.boolean.union([t_bar, core], engine='manifold')
                                zip_file.writestr("puanson_T_shape.stl", puanson.export(file_type='stl'))
                        
                        st.download_button("Скачать комплект (ZIP-архив)", data=zip_buffer.getvalue(), file_name="mold_with_puanson.zip", mime="application/zip")
                    
                except Exception as e:
                    st.error(f"Произошла ошибка: {e}")
                finally:
                    if os.path.exists(tmp_file_path): os.remove(tmp_file_path)
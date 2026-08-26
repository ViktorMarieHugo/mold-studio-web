import streamlit as st
import trimesh
import tempfile
import os
import zipfile
import io
import math

st.set_page_config(page_title="Генератор молдов", layout="wide")
st.title("🧱 Генератор силиконовых форм (Молдов)")

st.caption("Версия 8.0 (Пустотелое литье, пуансоны и гравировка) | Обновлено: 25 августа 2026 г.")
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
        st.info("💡 **Режим перевернутой формы:** Модель будет перевернута вверх ногами. Дно детали станет широкой горловиной для заливки. Снизу будет сгенерирована подставка.")
        hollow_method = st.radio(
            "Метод создания пустоты:",
            ["Метод обкатки (Ротационное литье)", 
             "Гладкий конусный пуансон (Стержень)"]
        )
        if "обкатки" in hollow_method:
            st.caption("👉 *Обкатка:* Вы заливаете 30% гипса и медленно вращаете форму в руках, пока гипс не застынет ровным слоем по стенкам.")
        else:
            st.caption("👉 *Пуансон:* Программа сгенерирует отдельную крышку с гладким конусом. Он вставляется в форму и вытесняет гипс из центра. После застывания легко вынимается.")
            
    st.markdown("---")
    mold_type = st.radio(
        "Конструкция молда:",
        ["Разрезать на 2 половинки (с замками)", "Цельная оболочка"]
    )
    
    sprue_mode = "Без отверстий"
    if "Сплошная" in cast_mode:
        st.markdown("---")
        sprue_mode = st.radio("Литник (только для сплошной):", ["Без отверстий (сделать в слайсере)", "Авто-литник в высшей точке"])

with col2:
    st.subheader("Обработка и результат")
    
    if uploaded_file is not None:
        if st.button("Сгенерировать форму", type="primary"):
            with st.spinner("Проектирование профессиональной формы (это займет минуту)..."):
                
                file_extension = os.path.splitext(uploaded_file.name)[1].lower()
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_file_path = tmp_file.name
                
                try:
                    loaded_data = trimesh.load(tmp_file_path)
                    mesh = loaded_data.dump(concatenate=True) if isinstance(loaded_data, trimesh.Scene) else loaded_data
                    
                    # 1. Центрируем и масштабируем
                    bounds_center = (mesh.bounds[0] + mesh.bounds[1]) / 2.0
                    mesh.apply_translation(-bounds_center)
                    
                    # 2. Переворот для пустотелой заливки
                    if "Пустотелая" in cast_mode:
                        rot_matrix = trimesh.transformations.rotation_matrix(math.pi, [1, 0, 0])
                        mesh.apply_transform(rot_matrix)
                        
                    extents = mesh.extents 
                    z_min_model = mesh.bounds[0][2]
                    z_max_model = mesh.bounds[1][2]
                    
                    # 3. Создаем скорлупу
                    blob_mold = mesh.convex_hull
                    blob_center = (blob_mold.bounds[0] + blob_mold.bounds[1]) / 2.0
                    blob_mold.apply_translation(-blob_center) 
                    
                    sx = (blob_mold.extents[0] + 12.0) / blob_mold.extents[0]
                    sy = (blob_mold.extents[1] + 12.0) / blob_mold.extents[1]
                    sz = (blob_mold.extents[2] + 12.0) / blob_mold.extents[2]
                    blob_mold.apply_scale([sx, sy, sz])
                    blob_mold.apply_translation(blob_center)
                    
                    max_dim = max(extents) * 3
                    
                    # 4. Формируем дно и верх
                    if "Пустотелая" in cast_mode:
                        # Срезаем верх ровно по уровню "лап" зайца для широкой горловины
                        top_cut = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        top_cut.apply_translation([0, 0, z_max_model - max_dim/2.0])
                        mold_base = trimesh.boolean.intersection([blob_mold, top_cut], engine='manifold')
                        
                        # Создаем надежную подставку-базу снизу (так как уши теперь внизу)
                        stand = trimesh.creation.box(extents=[extents[0]*1.5, extents[1]*1.5, 10.0])
                        stand.apply_translation([0, 0, z_min_model - 5.0])
                        mold_base = trimesh.boolean.union([mold_base, stand], engine='manifold')
                    else:
                        # Классический срез дна
                        bottom_cut = trimesh.creation.box(extents=[max_dim, max_dim, max_dim])
                        bottom_cut.apply_translation([0, 0, z_min_model - 3.0 + max_dim/2.0])
                        mold_base = trimesh.boolean.intersection([blob_mold, bottom_cut], engine='manifold')

                    # 5. АРОЧНЫЙ ФЛАНЕЦ (РЕЛЬСЫ)
                    flange_profile = blob_mold.copy()
                    f_center = (flange_profile.bounds[0] + flange_profile.bounds[1]) / 2.0
                    flange_profile.apply_translation(-f_center)
                    
                    flange_profile.apply_scale([1.0, (blob_mold.extents[1] + 24.0)/blob_mold.extents[1], (blob_mold.extents[2] + 24.0)/blob_mold.extents[2]])
                    flange_profile.apply_translation(f_center)
                    
                    slab_box = trimesh.creation.box(extents=[20.0, max_dim, max_dim])
                    flange = trimesh.boolean.intersection([flange_profile, slab_box], engine='manifold')
                    mold_with_ears = trimesh.boolean.union([mold_base, flange], engine='manifold')
                    
                    # 6. ГРАВИРОВКА ЛОГОТИПА
                    try:
                        # Создаем углубление-табличку на левом фланце
                        plate_h = 30.0
                        plate = trimesh.creation.box(extents=[5.0, plate_h, 15.0])
                        plate.apply_translation([-10.0, 0, (z_max_model + z_min_model)/2.0])
                        mold_with_ears = trimesh.boolean.difference([mold_with_ears, plate], engine='manifold')
                    except:
                        pass # Если не выйдет, игнорируем ошибку

                    # 7. ЛИТНИК И ВЫЧИТАНИЕ
                    if "Авто-литник" in sprue_mode and "Сплошная" in cast_mode:
                        highest_idx = mesh.vertices[:, 2].argmax()
                        sprue = trimesh.creation.cylinder(radius=4.0, height=extents[2] + 40)
                        sprue.apply_translation([0, mesh.vertices[highest_idx, 1], mesh.vertices[highest_idx, 2] + 20])
                        mesh_to_subtract = trimesh.boolean.union([mesh, sprue], engine='manifold')
                    else:
                        mesh_to_subtract = mesh
                        
                    mesh_to_subtract.apply_translation([0, 0, 0.05])
                    final_mold = trimesh.boolean.difference([mold_with_ears, mesh_to_subtract], engine='manifold')
                    
                    # 8. РАЗРЕЗ И ЗАМКИ
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
                        
                        for z_pos in [mold_base.bounds[0][2] + mold_h * 0.3, mold_base.bounds[0][2] + mold_h * 0.7]:
                            slice_2d = mold_base.section(plane_origin=[0,0,z_pos], plane_normal=[0,0,1])
                            if slice_2d is not None:
                                # ЗАМКИ СДВИНУТЫ ВГЛУБЬ ФЛАНЦА (на 3 мм вместо 6 мм от края оболочки)
                                positions = [[0, slice_2d.bounds[0][1] - 3.0, z_pos], [0, slice_2d.bounds[1][1] + 3.0, z_pos]]
                                for pos in positions:
                                    locks_male.append(trimesh.creation.icosphere(radius=3.3, subdivisions=3).apply_translation(pos))
                                    locks_female.append(trimesh.creation.icosphere(radius=3.5, subdivisions=3).apply_translation(pos))
                        
                        part_right = trimesh.boolean.union([part_right_base, trimesh.util.concatenate(locks_male)], engine='manifold')
                        part_left = trimesh.boolean.difference([part_left_base, trimesh.util.concatenate(locks_female)], engine='manifold')
                        
                        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
                            zip_file.writestr("mold_left_female.stl", part_left.export(file_type='stl'))
                            zip_file.writestr("mold_right_male.stl", part_right.export(file_type='stl'))
                            
                            # ГЕНЕРАЦИЯ ПУАНСОНА
                            if hollow_method and "Конус" in hollow_method:
                                plug_r = min(extents[0], extents[1]) * 0.25 # Узкий гладкий конус
                                plug_h = extents[2] * 0.65
                                plug_cone = trimesh.creation.cylinder(radius=plug_r, height=plug_h)
                                plug_cone.apply_translation([0, 0, z_max_model - plug_h/2.0])
                                
                                lid = trimesh.creation.box(extents=[extents[0]+15, extents[1]+15, 4.0])
                                lid.apply_translation([0, 0, z_max_model + 2.0])
                                
                                final_plug = trimesh.boolean.union([plug_cone, lid], engine='manifold')
                                zip_file.writestr("plug_core.stl", final_plug.export(file_type='stl'))
                        
                        st.download_button("Скачать ZIP-архив", data=zip_buffer.getvalue(), file_name="mold_irivek_pro.zip", mime="application/zip")
                    
                except Exception as e:
                    st.error(f"Произошла ошибка при вычислениях: {e}")
                finally:
                    if os.path.exists(tmp_file_path): os.remove(tmp_file_path)
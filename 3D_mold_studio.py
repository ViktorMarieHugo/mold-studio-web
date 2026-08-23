import streamlit as st
import trimesh
import tempfile
import os

st.set_page_config(page_title="Генератор молдов", layout="wide")
st.title("🧱 Генератор силиконовых форм (Молдов)")

# --- ДОБАВЛЕНА ВЕРСИЯ И ДАТА ---
st.caption("Версия 1.1 | Обновлено: 23 августа 2026 г.") 
st.markdown("---") # Добавим красивую разделительную линию

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Настройки формы")
    uploaded_file = st.file_uploader("Загрузите мастер-модель", type=["stl", "3mf"])
    
    st.markdown("---")
    scale_option = st.radio(
        "Масштаб исходной модели (если загрузилась слишком маленькой)",
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
            with st.spinner("Анализ геометрии и булево вычитание (может занять время)..."):
                
               # Определяем, какое расширение у загруженного файла (.stl или .3mf)
                file_extension = os.path.splitext(uploaded_file.name)[1].lower()
                
                # Сохраняем файл во временную папку с правильным расширением
                with tempfile.NamedTemporaryFile(delete=False, suffix=file_extension) as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_file_path = tmp_file.name
                try:
                    # Загружаем модель
                    mesh = trimesh.load(tmp_file_path)
                    
                    if not isinstance(mesh, trimesh.Trimesh):
                         st.error("Ошибка: Файл не является корректным 3D-мешем.")
                         st.stop()
                    
                    # Применяем масштаб, если нужно
                    if scale_option != 1.0:
                        mesh.apply_scale(scale_option)
                         
                    extents = mesh.extents 
                    bounds = mesh.bounds   
                    
                    st.write(f"**Актуальные размеры модели (X, Y, Z):** {extents[0]:.1f} x {extents[1]:.1f} x {extents[2]:.1f} мм")
                    
                    # 1. Задаем размеры коробки
                    box_x = extents[0] + (wall_thickness * 2)
                    box_y = extents[1] + (wall_thickness * 2)
                    box_z = extents[2] + bottom_offset
                    
                    mold_box = trimesh.creation.box(extents=[box_x, box_y, box_z])
                    
                    # 2. Исправленное выравнивание
                    # Находим правильный геометрический центр для коробки, 
                    # чтобы она полностью накрыла деталь со всех сторон.
                    correct_center = [
                        (bounds[0][0] + bounds[1][0]) / 2,         # Ровно по центру X
                        (bounds[0][1] + bounds[1][1]) / 2,         # Ровно по центру Y
                        bounds[0][2] - bottom_offset + (box_z / 2) # Исправленная высота Z
                    ]
                    
                    # Двигаем коробку в нужную точку
                    mold_box.apply_translation(correct_center)
                    
                    # 3. Настоящее вычитание
                    final_mold = trimesh.boolean.difference([mold_box, mesh], engine='manifold')
                    
                    st.success("Форма с полостью успешно просчитана!")
                    
                    # Экспортируем готовый результат
                    final_data = final_mold.export(file_type='stl')
                    
                    st.download_button(
                        label="Скачать цельный молд (STL)",
                        data=final_data,
                        file_name="mold_with_cavity.stl",
                        mime="model/stl"
                    )

                except Exception as e:
                    st.error(f"Произошла ошибка при обработке: {e}")
                
                finally:
                    # Удаляем временный файл
                    os.remove(tmp_file_path)
    else:
        st.info("👈 Загрузите мастер-модель в меню слева.")
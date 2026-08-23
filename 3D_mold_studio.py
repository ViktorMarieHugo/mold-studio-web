import streamlit as st
import trimesh
import numpy as np
import tempfile
import os

st.set_page_config(page_title="Генератор молдов", layout="wide")
st.title("🧱 Генератор силиконовых форм (Молдов)")

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Настройки формы")
    uploaded_file = st.file_uploader("Загрузите мастер-модель", type=["stl"])
    
    wall_thickness = st.slider("Толщина стенок формы (мм)", min_value=2, max_value=15, value=5, step=1)
    
    # Ползунок для отступа снизу (чтобы модель не провалилась насквозь)
    bottom_offset = st.slider("Толщина дна молда (мм)", min_value=1, max_value=10, value=3, step=1)

with col2:
    st.subheader("Обработка и результат")
    
    if uploaded_file is not None:
        st.success(f"Файл '{uploaded_file.name}' загружен!")
        
        if st.button("Сгенерировать базовый блок", type="primary"):
            with st.spinner("Анализ геометрии..."):
                
                # 1. Сохраняем загруженный файл во временную папку, чтобы trimesh мог его прочитать
                with tempfile.NamedTemporaryFile(delete=False, suffix='.stl') as tmp_file:
                    tmp_file.write(uploaded_file.getvalue())
                    tmp_file_path = tmp_file.name
                
                try:
                    # 2. Загружаем модель через trimesh
                    mesh = trimesh.load(tmp_file_path)
                    
                    # Проверяем, что загрузился именно меш (иногда файлы могут быть сломаны)
                    if not isinstance(mesh, trimesh.Trimesh):
                         st.error("Ошибка: Файл не является корректным 3D-мешем.")
                         st.stop()
                         
                    # 3. Узнаем габариты загруженной модели (bounding box)
                    extents = mesh.extents # Размеры по X, Y, Z
                    bounds = mesh.bounds   # Координаты минимальной и максимальной точек
                    
                    st.write(f"**Размеры вашей модели (X, Y, Z):** {extents[0]:.1f} x {extents[1]:.1f} x {extents[2]:.1f} мм")
                    
                    # 4. Рассчитываем размеры коробки-опалубки
                    # Ширина и длина = размер модели + толщина стенок с двух сторон
                    box_x = extents[0] + (wall_thickness * 2)
                    box_y = extents[1] + (wall_thickness * 2)
                    # Высота = высота модели + толщина дна
                    box_z = extents[2] + bottom_offset
                    
                    st.write(f"**Размер генерируемого блока:** {box_x:.1f} x {box_y:.1f} x {box_z:.1f} мм")
                    
                    # 5. Создаем 3D-куб (опалубку)
                    mold_box = trimesh.creation.box(extents=[box_x, box_y, box_z])
                    
                    # Перемещаем куб так, чтобы его дно было ровно под моделью
                    # (выравнивание центров)
                    center_offset = mesh.centroid - mold_box.centroid
                    center_offset[2] = bounds[0][2] - (box_z / 2) + bottom_offset # Корректируем по Z (высоте)
                    mold_box.apply_translation(center_offset)
                    
                    # --- Здесь в будущем будет булево вычитание ---
                    # result_mesh = mold_box.difference(mesh) 
                    
                    st.success("Блок-опалубка успешно просчитана!")
                    
                    # Для проверки пока даем скачать просто сгенерированную коробку
                    # Экспортируем меш коробки в байты
                    box_data = mold_box.export(file_type='stl')
                    
                    st.download_button(
                        label="Скачать тестовый блок (STL)",
                        data=box_data,
                        file_name="test_mold_box.stl",
                        mime="model/stl"
                    )

                except Exception as e:
                    st.error(f"Произошла ошибка при обработке: {e}")
                
                finally:
                    # Удаляем временный файл, чтобы не засорять память
                    os.remove(tmp_file_path)
    else:
        st.info("👈 Загрузите мастер-модель в меню слева.")
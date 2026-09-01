from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
import math
from pathlib import Path
import zipfile

import manifold3d
import numpy as np
import trimesh


SUPPORTED_FORMATS = {"stl", "3mf"}


class MoldGenerationError(ValueError):
    """An input or geometry error that can be shown directly to the user."""


@dataclass(frozen=True)
class MoldKit:
    zip_bytes: bytes
    silicone_volume_ml: float
    plastic_volume_ml: float
    model_size_mm: tuple[float, float, float]
    mold_size_mm: tuple[float, float, float]
    base_shape: str
    source_faces: int
    tooling_faces: int


def _load_mesh(file_bytes: bytes, file_type: str) -> trimesh.Trimesh:
    extension = file_type.lower().lstrip(".")
    if extension not in SUPPORTED_FORMATS:
        raise MoldGenerationError("Поддерживаются только файлы STL и 3MF.")
    if not file_bytes:
        raise MoldGenerationError("Загруженный файл пуст.")

    try:
        loaded = trimesh.load(
            BytesIO(file_bytes),
            file_type=extension,
            force="scene",
            process=True,
        )
    except Exception as exc:
        raise MoldGenerationError(
            "Не удалось прочитать модель. Проверьте, что файл не повреждён."
        ) from exc

    mesh = loaded.to_geometry() if isinstance(loaded, trimesh.Scene) else loaded
    if not isinstance(mesh, trimesh.Trimesh) or mesh.faces.size == 0:
        raise MoldGenerationError("В файле не найдено треугольной 3D-геометрии.")

    mesh = mesh.copy()
    mesh.process(validate=True)
    mesh.remove_unreferenced_vertices()
    trimesh.repair.fix_normals(mesh, multibody=True)

    if not np.isfinite(mesh.vertices).all():
        raise MoldGenerationError("В модели есть некорректные координаты вершин.")
    if not mesh.is_watertight:
        raise MoldGenerationError(
            "Модель должна быть замкнутой (watertight), без отверстий и открытых рёбер."
        )
    if not mesh.is_winding_consistent:
        raise MoldGenerationError("У модели перепутано направление части полигонов.")
    if mesh.volume <= 0:
        mesh.invert()
    if mesh.volume <= 0:
        raise MoldGenerationError("Модель не образует корректный замкнутый объём.")

    components = mesh.split(only_watertight=False)
    if len(components) != 1:
        raise MoldGenerationError(
            "Модель должна состоять из одного связного тела. Объедините отдельные части перед загрузкой."
        )

    extents = np.asarray(mesh.extents, dtype=float)
    if np.any(extents < 1.0):
        raise MoldGenerationError("Один из размеров модели меньше 1 мм.")
    if np.any(extents > 400.0):
        raise MoldGenerationError(
            "Размер модели превышает 400 мм. STL считается заданным в миллиметрах."
        )

    return mesh


def _find_flat_base(mesh: trimesh.Trimesh) -> tuple[np.ndarray, np.ndarray]:
    z_min = float(mesh.bounds[0, 2])
    tolerance = max(0.02, float(mesh.extents.max()) * 1e-5)
    face_vertices = mesh.vertices[mesh.faces]
    on_base = np.all(np.abs(face_vertices[:, :, 2] - z_min) <= tolerance, axis=1)
    downward = mesh.face_normals[:, 2] < -0.9
    base_faces = np.flatnonzero(on_base & downward)

    if base_faces.size == 0:
        raise MoldGenerationError(
            "Не найдено плоское основание. Перед загрузкой поставьте модель вертикально "
            "и сделайте её нижнюю грань плоской."
        )

    areas = mesh.area_faces[base_faces]
    base_area = float(areas.sum())
    if base_area < 1.0:
        raise MoldGenerationError(
            "Площадь плоского основания слишком мала для крепления к планке."
        )

    triangles = mesh.triangles[base_faces]
    center_xy = np.average(triangles.mean(axis=1)[:, :2], axis=0, weights=areas)
    vertices_xy = triangles[:, :, :2].reshape(-1, 2)
    base_size = np.ptp(vertices_xy, axis=0)
    return np.asarray(center_xy, dtype=float), np.asarray(base_size, dtype=float)


def _orient_master(mesh: trimesh.Trimesh) -> tuple[trimesh.Trimesh, np.ndarray, np.ndarray]:
    base_center, base_size = _find_flat_base(mesh)
    bounds_center_xy = (mesh.bounds[0, :2] + mesh.bounds[1, :2]) / 2.0
    z_min = float(mesh.bounds[0, 2])

    oriented = mesh.copy()
    oriented.apply_translation(
        [-float(bounds_center_xy[0]), -float(bounds_center_xy[1]), -z_min]
    )
    oriented.apply_transform(
        trimesh.transformations.rotation_matrix(math.pi, [1.0, 0.0, 0.0])
    )

    transformed_base_center = np.array(
        [
            base_center[0] - bounds_center_xy[0],
            -(base_center[1] - bounds_center_xy[1]),
        ],
        dtype=float,
    )
    return oriented, transformed_base_center, base_size


def _to_manifold(mesh: trimesh.Trimesh) -> manifold3d.Manifold:
    raw_mesh = manifold3d.Mesh(
        vert_properties=np.ascontiguousarray(mesh.vertices, dtype=np.float32),
        tri_verts=np.ascontiguousarray(mesh.faces, dtype=np.uint32),
    )
    solid = manifold3d.Manifold(raw_mesh)
    if solid.status() != manifold3d.Error.NoError or solid.is_empty():
        raise MoldGenerationError(
            "Геометрическое ядро не смогло преобразовать модель в корректное тело."
        )
    return solid


def _to_trimesh(
    solid: manifold3d.Manifold,
    part_name: str = "деталь",
) -> trimesh.Trimesh:
    if solid.status() != manifold3d.Error.NoError or solid.is_empty():
        raise MoldGenerationError(
            f"Одна из деталей получилась пустой или повреждённой ({solid.status()})."
        )
    # Boolean products can retain duplicated property vertices along source-mesh
    # boundaries. Resetting ancestry emits one welded positional mesh for STL.
    raw = solid.as_original().to_mesh64()
    vertices = np.asarray(raw.vert_properties[:, :3], dtype=np.float64)
    faces = np.asarray(raw.tri_verts, dtype=np.int64)
    last_mesh: trimesh.Trimesh | None = None

    # Manifold can legitimately emit very thin triangles after booleans. Removing
    # them creates tiny holes (typically six open edges on detailed 3MF models),
    # so preserve every face and only weld coincident vertices. Try increasingly
    # tolerant, still sub-micron-to-micron welds for cross-platform float variance.
    for digits_vertex in (None, 8, 7, 6, 5, 4):
        mesh = trimesh.Trimesh(vertices=vertices, faces=faces, process=False)
        if digits_vertex is not None:
            mesh.merge_vertices(
                merge_tex=True,
                merge_norm=True,
                digits_vertex=digits_vertex,
            )
        mesh.remove_unreferenced_vertices()
        trimesh.repair.fix_normals(mesh, multibody=True)
        last_mesh = mesh
        if mesh.faces.size > 0 and mesh.is_watertight and mesh.volume > 0:
            return mesh

    assert last_mesh is not None
    edge_counts = np.bincount(last_mesh.edges_unique_inverse)
    open_edges = int(np.count_nonzero(edge_counts == 1))
    crowded_edges = int(np.count_nonzero(edge_counts > 2))
    raise MoldGenerationError(
        f"Выходная деталь «{part_name}» не является замкнутым телом "
        f"(грани: {len(last_mesh.faces)}, watertight: {last_mesh.is_watertight}, "
        f"объём: {last_mesh.volume:.3f}, open edges: {open_edges}, "
        f"nonmanifold edges: {crowded_edges})."
    )


def _box(size: tuple[float, float, float], center: tuple[float, float, float]) -> manifold3d.Manifold:
    return manifold3d.Manifold.cube(size, center=True).translate(center)


def _base_solid(
    shape: str,
    span_x: float,
    span_y: float,
    height: float,
    center_z: float,
) -> tuple[manifold3d.Manifold, tuple[float, float]]:
    if shape == "square":
        side = max(span_x, span_y)
        return _box((side, side, height), (0.0, 0.0, center_z)), (side, side)
    if shape == "round":
        radius = math.hypot(span_x, span_y) / 2.0
        cylinder = manifold3d.Manifold.cylinder(
            height,
            radius,
            circular_segments=64,
            center=True,
        ).translate((0.0, 0.0, center_z))
        return cylinder, (radius * 2.0, radius * 2.0)
    raise MoldGenerationError("Неизвестная форма основания.")


def _clip_below_top(
    solid: manifold3d.Manifold,
    bottom_z: float,
    xy_size: float,
    top_z: float = 0.0,
) -> manifold3d.Manifold:
    clip_bottom = bottom_z - 1.0
    height = top_z - clip_bottom
    clip = _box(
        (xy_size, xy_size, height),
        (0.0, 0.0, clip_bottom + height / 2.0),
    )
    return solid ^ clip


def _simplify_for_tooling(
    master: manifold3d.Manifold,
    silicone_thickness: float,
) -> tuple[manifold3d.Manifold, float]:
    tolerance = max(0.05, min(0.20, silicone_thickness * 0.02))
    simplified = master.simplify(tolerance)
    while simplified.num_tri() > 20_000 and tolerance < 0.8:
        tolerance = min(0.8, tolerance * 1.6)
        simplified = master.simplify(tolerance)
    if simplified.num_tri() > 35_000:
        raise MoldGenerationError(
            "Модель слишком детализирована для облачной генерации. Уменьшите число полигонов."
        )
    return simplified, tolerance


def _prepare_for_print(mesh: trimesh.Trimesh, flip_master: bool = False) -> trimesh.Trimesh:
    result = mesh.copy()
    if flip_master:
        result.apply_transform(
            trimesh.transformations.rotation_matrix(math.pi, [1.0, 0.0, 0.0])
        )
    center_xy = (result.bounds[0, :2] + result.bounds[1, :2]) / 2.0
    result.apply_translation(
        [-float(center_xy[0]), -float(center_xy[1]), -float(result.bounds[0, 2])]
    )
    return result


def _stl_bytes(mesh: trimesh.Trimesh) -> bytes:
    exported = mesh.export(file_type="stl")
    return exported.encode("utf-8") if isinstance(exported, str) else bytes(exported)


def generate_mold_kit(
    file_bytes: bytes,
    file_type: str,
    silicone_thickness: float,
    plastic_wall: float,
    base_shape: str = "square",
) -> MoldKit:
    if not 5.0 <= silicone_thickness <= 30.0:
        raise MoldGenerationError("Толщина силикона должна быть от 5 до 30 мм.")
    if not 2.0 <= plastic_wall <= 10.0:
        raise MoldGenerationError("Толщина пластика должна быть от 2 до 10 мм.")

    source_mesh = _load_mesh(file_bytes, file_type)
    model_size = tuple(float(value) for value in source_mesh.extents)
    oriented_mesh, base_center_xy, base_size = _orient_master(source_mesh)
    master = _to_manifold(oriented_mesh)
    tooling_source, tolerance = _simplify_for_tooling(master, silicone_thickness)

    # The simplification can move the tooling surface by at most `tolerance`.
    # Adding it to the radius preserves the user-selected minimum silicone wall.
    inner_radius = float(silicone_thickness + tolerance)
    outer_radius = float(inner_radius + plastic_wall)
    sphere_segments = 20
    inner_offset = tooling_source.minkowski_sum(
        manifold3d.Manifold.sphere(inner_radius, sphere_segments)
    )
    outer_offset = tooling_source.minkowski_sum(
        manifold3d.Manifold.sphere(outer_radius, sphere_segments)
    )

    inner_bounds = inner_offset.bounding_box()
    span_x = float(inner_bounds[3] - inner_bounds[0])
    span_y = float(inner_bounds[4] - inner_bounds[1])
    model_bottom = float(oriented_mesh.bounds[0, 2])
    inner_bottom = model_bottom - inner_radius
    outer_bottom = model_bottom - outer_radius
    base_height = max(4.0, min(8.0, silicone_thickness * 0.4))

    inner_base, base_span = _base_solid(
        base_shape,
        span_x,
        span_y,
        base_height,
        inner_bottom + base_height / 2.0,
    )
    outer_base, outer_base_span = _base_solid(
        base_shape,
        base_span[0] + 2.0 * plastic_wall,
        base_span[1] + 2.0 * plastic_wall,
        base_height + 2.0 * plastic_wall,
        outer_bottom + (base_height + 2.0 * plastic_wall) / 2.0,
    )

    working_size = max(
        float(oriented_mesh.extents.max()) + 2.0 * outer_radius,
        outer_base_span[0],
        outer_base_span[1],
    ) * 2.5
    inner_raw = inner_offset + inner_base
    silicone_body = _clip_below_top(
        inner_raw,
        inner_bottom,
        working_size,
    )
    outer_body = _clip_below_top(
        outer_offset + outer_base,
        outer_bottom,
        working_size,
    )
    silicone_cutter = _clip_below_top(
        inner_raw,
        inner_bottom,
        working_size,
        top_z=max(1.0, plastic_wall * 0.5),
    )
    pot = outer_body - silicone_cutter

    # A continuous flange follows the entire split contour. The silicone cavity
    # is subtracted from the flange blank, so the web joins the shell everywhere
    # without intruding into the future silicone mold. Thicker outer rails give
    # the clamps a rigid grip and carry the spherical alignment locks.
    pin_radius = min(3.5, max(2.2, plastic_wall * 0.9))
    rail_x = max(2.0 * pin_radius + 1.0, 2.0 * plastic_wall + 2.0)
    rail_depth = max(10.0, plastic_wall * 3.0)
    rail_start = base_span[1] / 2.0 + plastic_wall * 0.5
    rail_center_y = rail_start + rail_depth / 2.0
    rail_outer_y = rail_start + rail_depth
    rail_height = -outer_bottom
    rail_center_z = outer_bottom + rail_height / 2.0
    flange_web_x = max(4.0, plastic_wall * 1.5)
    flange_blank = _box(
        (flange_web_x, 2.0 * rail_outer_y, rail_height),
        (0.0, 0.0, rail_center_z),
    )
    flange_web = flange_blank - silicone_cutter
    front_rail = _box(
        (rail_x, rail_depth, rail_height),
        (0.0, rail_center_y, rail_center_z),
    )
    rear_rail = _box(
        (rail_x, rail_depth, rail_height),
        (0.0, -rail_center_y, rail_center_z),
    )
    pot_with_rails = manifold3d.Manifold.batch_boolean(
        [pot, flange_web, front_rail, rear_rail], manifold3d.OpType.Add
    )

    right_base, left_base = pot_with_rails.split_by_plane((1.0, 0.0, 0.0), 0.0)
    available_height = -outer_bottom
    if available_height >= 28.0:
        lock_z = [outer_bottom + available_height * 0.32, outer_bottom + available_height * 0.70]
    else:
        lock_z = [outer_bottom + available_height * 0.55]

    male_locks: list[manifold3d.Manifold] = []
    female_locks: list[manifold3d.Manifold] = []
    lock_center_x = -0.25
    for z_position in lock_z:
        for y_position in (-rail_center_y, rail_center_y):
            male_locks.append(
                manifold3d.Manifold.sphere(pin_radius, 20).translate(
                    (lock_center_x, y_position, z_position)
                )
            )
            female_locks.append(
                manifold3d.Manifold.sphere(pin_radius + 0.25, 20).translate(
                    (lock_center_x, y_position, z_position)
                )
            )

    male_union = manifold3d.Manifold.batch_boolean(male_locks, manifold3d.OpType.Add)
    female_union = manifold3d.Manifold.batch_boolean(female_locks, manifold3d.OpType.Add)
    right_part = right_base + male_union
    left_part = left_base - female_union

    # A narrow bar across the two external rails leaves two large silicone-pour
    # openings on its sides. Its bottom is exactly the master model's base plane.
    pour_clearance = max(3.0, silicone_thickness * 0.5)
    desired_plank_width = max(8.0, min(18.0, float(base_size[0]) * 0.5))
    maximum_plank_width = max(6.0, base_span[0] - 2.0 * pour_clearance)
    plank_width = min(desired_plank_width, maximum_plank_width)
    plank_overhang = 4.0
    plank_length = 2.0 * (rail_outer_y + plank_overhang)
    plank_height = 8.0
    plank = _box(
        (plank_width, plank_length, plank_height),
        (
            float(base_center_xy[0]),
            0.0,
            plank_height / 2.0,
        ),
    )
    puanson = master + plank

    puanson_mesh = _prepare_for_print(
        _to_trimesh(puanson, "мастер-пуансон"),
        flip_master=True,
    )
    left_mesh = _prepare_for_print(_to_trimesh(left_part, "левая опалубка"))
    right_mesh = _prepare_for_print(_to_trimesh(right_part, "правая опалубка"))

    silicone_volume = max(0.0, silicone_body.volume() - master.volume())
    plastic_volume = max(0.0, left_part.volume() + right_part.volume())
    mold_bounds = silicone_body.bounding_box()
    mold_size = (
        float(mold_bounds[3] - mold_bounds[0]),
        float(mold_bounds[4] - mold_bounds[1]),
        float(mold_bounds[5] - mold_bounds[2]),
    )

    zip_buffer = BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("1_master_puanson.stl", _stl_bytes(puanson_mesh))
        archive.writestr("2_formwork_left.stl", _stl_bytes(left_mesh))
        archive.writestr("3_formwork_right.stl", _stl_bytes(right_mesh))

    return MoldKit(
        zip_bytes=zip_buffer.getvalue(),
        silicone_volume_ml=silicone_volume / 1_000.0,
        plastic_volume_ml=plastic_volume / 1_000.0,
        model_size_mm=model_size,
        mold_size_mm=mold_size,
        base_shape=base_shape,
        source_faces=int(source_mesh.faces.shape[0]),
        tooling_faces=int(tooling_source.num_tri()),
    )


def extension_from_name(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")

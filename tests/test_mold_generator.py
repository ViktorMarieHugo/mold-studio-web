from __future__ import annotations

from io import BytesIO
import unittest
import zipfile

import trimesh

from mold_generator import MoldGenerationError, generate_mold_kit


def sample_master_bytes() -> bytes:
    mesh = trimesh.creation.box(extents=(20.0, 16.0, 30.0))
    mesh.apply_translation((0.0, 0.0, 15.0))
    return bytes(mesh.export(file_type="stl"))


def figurine_master_bytes() -> bytes:
    body = trimesh.creation.box(extents=(18.0, 14.0, 24.0))
    body.apply_translation((0.0, 0.0, 12.0))
    head = trimesh.creation.icosphere(subdivisions=2, radius=8.0)
    head.apply_translation((0.0, 0.0, 27.0))
    left_ear = trimesh.creation.box(extents=(4.0, 5.0, 16.0))
    left_ear.apply_translation((-4.5, 0.0, 39.0))
    right_ear = trimesh.creation.box(extents=(4.0, 5.0, 16.0))
    right_ear.apply_translation((4.5, 0.0, 39.0))
    mesh = trimesh.boolean.union(
        [body, head, left_ear, right_ear],
        engine="manifold",
    )
    return bytes(mesh.export(file_type="stl"))


class MoldGeneratorTests(unittest.TestCase):
    def test_generates_three_watertight_stl_files(self) -> None:
        kit = generate_mold_kit(
            sample_master_bytes(),
            "stl",
            silicone_thickness=5.0,
            plastic_wall=2.0,
            base_shape="square",
        )

        self.assertGreater(kit.silicone_volume_ml, 0.0)
        self.assertGreater(kit.plastic_volume_ml, 0.0)
        self.assertEqual(tuple(round(value) for value in kit.model_size_mm), (20, 16, 30))

        with zipfile.ZipFile(BytesIO(kit.zip_bytes)) as archive:
            self.assertEqual(
                archive.namelist(),
                [
                    "1_master_puanson.stl",
                    "2_formwork_left.stl",
                    "3_formwork_right.stl",
                ],
            )
            for filename in archive.namelist():
                mesh = trimesh.load(
                    BytesIO(archive.read(filename)),
                    file_type="stl",
                    force="mesh",
                )
                self.assertTrue(mesh.is_watertight, filename)
                self.assertGreater(mesh.volume, 0.0, filename)
                self.assertAlmostEqual(float(mesh.bounds[0, 2]), 0.0, places=4)

            for filename in ("2_formwork_left.stl", "3_formwork_right.stl"):
                formwork = trimesh.load(
                    BytesIO(archive.read(filename)),
                    file_type="stl",
                    force="mesh",
                )
                cut_height = float(formwork.extents[2]) * 0.25
                faces_above_base = formwork.triangles_center[:, 2] > cut_height
                upper_part = formwork.submesh(
                    [faces_above_base],
                    append=True,
                    repair=False,
                )
                connected_components = upper_part.split(only_watertight=False)
                self.assertEqual(
                    len(connected_components),
                    1,
                    f"Clamp rails must remain connected to the shell: {filename}",
                )

    def test_rejects_master_without_flat_base(self) -> None:
        sphere = trimesh.creation.icosphere(subdivisions=2, radius=10.0)
        sphere.apply_translation((0.0, 0.0, 10.0))
        with self.assertRaisesRegex(MoldGenerationError, "плоское основание"):
            generate_mold_kit(
                bytes(sphere.export(file_type="stl")),
                "stl",
                silicone_thickness=5.0,
                plastic_wall=2.0,
            )

    def test_generates_round_base_for_nonconvex_figurine(self) -> None:
        kit = generate_mold_kit(
            figurine_master_bytes(),
            "stl",
            silicone_thickness=7.0,
            plastic_wall=3.0,
            base_shape="round",
        )

        self.assertEqual(kit.base_shape, "round")
        self.assertGreater(kit.silicone_volume_ml, 0.0)
        self.assertGreater(len(kit.zip_bytes), 1_000)


if __name__ == "__main__":
    unittest.main()

from analysis.artifact_classifier import build_default_classifier
from metadata.base import MetadataGroup, MetadataItem, MetadataResult


def _image_record():
    return {
        "file_id": "f4eaa4d1-cf9b-4884-b05b-5c53750636f5",
        "name": "photo.jpg",
        "category": "Images",
        "mime": "image/jpeg",
        "output": "photo.jpg",
    }


def test_image_artifacts_are_derived_from_existing_metadata():
    result = MetadataResult(
        groups=(
            MetadataGroup(
                "EXIF",
                (
                    MetadataItem("Marque", "Canon"),
                    MetadataItem("Modèle", "EOS R6"),
                    MetadataItem("Logiciel", "Lightroom"),
                ),
            ),
            MetadataGroup("GPS", (MetadataItem("Latitude", "48.85660"), MetadataItem("Longitude", "2.35220"))),
        )
    )

    artifacts = build_default_classifier().classify(_image_record(), result)

    assert {artifact.identifier for artifact in artifacts} == {
        "image.exif",
        "image.gps",
        "image.camera",
        "image.modified",
    }
    assert any(artifact.label == "📷 Canon EOS R6" for artifact in artifacts)


def test_image_without_exif_is_marked_as_metadata_absent():
    artifacts = build_default_classifier().classify(_image_record(), MetadataResult())

    assert artifacts[0].identifier == "image.no_exif"


def test_classifier_reuses_its_result_for_the_same_file():
    classifier = build_default_classifier()
    record = _image_record()
    first = classifier.classify(record, MetadataResult())
    second = classifier.classify(record, MetadataResult())

    assert second is first

"""Direct tests for the production get_extension (R5-2).

The main suite class-patches get_extension away and asserts against a hand-kept
reimplementation in test_common, so the real file_id decoding + mime path never
runs. These tests exercise the real function with synthesized pyrogram file_ids.
"""

import unittest

from pyrogram.file_id import FileId, FileType, ThumbnailSource

from module.pyrogram_extension import _guess_extension, get_extension


def _media_file_id(file_type: FileType) -> str:
    """Encode a minimal-but-valid file_id for a non-photo media type."""
    return FileId(
        major=4,
        minor=30,
        file_type=file_type,
        dc_id=2,
        media_id=12345,
        access_hash=67890,
        volume_id=0,
        local_id=0,
    ).encode()


def _photo_file_id() -> str:
    """Encode a valid photo file_id (photo encoding needs thumbnail fields)."""
    return FileId(
        major=4,
        minor=30,
        file_type=FileType.PHOTO,
        dc_id=2,
        media_id=12345,
        access_hash=67890,
        volume_id=100,
        local_id=5,
        thumbnail_source=ThumbnailSource.THUMBNAIL,
        thumbnail_file_type=FileType.PHOTO,
        thumbnail_size="m",
    ).encode()


class GetExtensionTestCase(unittest.TestCase):
    def test_empty_file_id_is_unknown(self):
        self.assertEqual(get_extension("", None), ".unknown")
        self.assertEqual(get_extension("", "video/mp4", dot=False), "unknown")

    def test_photo_is_jpg(self):
        fid = _photo_file_id()
        self.assertEqual(get_extension(fid, None), ".jpg")
        self.assertEqual(get_extension(fid, None, dot=False), "jpg")

    def test_video_uses_mime_without_double_dot(self):
        # Regression: _guess_extension returns a dotted extension; get_extension
        # then prepended another dot, yielding "..mp4". Must be a single dot.
        fid = _media_file_id(FileType.VIDEO)
        self.assertEqual(get_extension(fid, "video/mp4"), ".mp4")
        self.assertEqual(get_extension(fid, "video/mp4", dot=False), "mp4")

    def test_voice_document_audio_use_mime(self):
        self.assertEqual(
            get_extension(_media_file_id(FileType.VOICE), "audio/ogg"), ".ogg"
        )
        self.assertEqual(
            get_extension(_media_file_id(FileType.DOCUMENT), "application/zip"),
            ".zip",
        )
        self.assertEqual(
            get_extension(_media_file_id(FileType.AUDIO), "audio/mpeg"), ".mp3"
        )

    def test_missing_mime_falls_back_to_type_default_without_crashing(self):
        # Regression: mimetypes.guess_extension(None) raises; get_extension must
        # tolerate media with no mime_type and use the per-type default.
        self.assertEqual(get_extension(_media_file_id(FileType.VIDEO), None), ".mp4")
        self.assertEqual(get_extension(_media_file_id(FileType.DOCUMENT), ""), ".zip")

    def test_guess_extension_is_dotless_and_none_safe(self):
        self.assertIsNone(_guess_extension(None))
        self.assertIsNone(_guess_extension(""))
        self.assertEqual(_guess_extension("video/mp4"), "mp4")


if __name__ == "__main__":
    unittest.main()

# Architecture des métadonnées

Le pipeline de métadonnées est indépendant de Qt, des aperçus et des modules
DFIR. Sa donnée primaire est `MetadataField` : un identifiant stable, une
catégorie, une valeur typée, une provenance, un niveau de confiance et un ordre
d'affichage. Les groupes affichés par le panneau de détails sont une projection
de compatibilité de ces champs ; ils ne constituent pas un second modèle de
données.

`MetadataProviderRegistry` est le point d'extension. Un nouveau format ajoute
une classe `MetadataProvider` avec un `provider_id` unique, une `priority`,
`supports(file_record)` et `extract(file_record)`. L'extracteur retourne une
itération de `MetadataField`, sans dictionnaire libre. Le module qui apporte le
format enregistre son provider ; `MetadataManager` n'a pas à être modifié.

Le manager appelle tous les providers compatibles. Pour un même `identifier`,
il garde la valeur du provider de priorité la plus élevée, puis celle dont la
confiance est la plus élevée à priorité égale. Les champs restants sont triés
par catégorie, ordre d'affichage, libellé et identifiant. Les erreurs d'un
provider sont isolées : les autres providers peuvent encore fournir leurs
champs. Le résultat agrégé est conservé par `MetadataCache`, indexé uniquement
par le `file_id` canonique.

Les catégories standard sont : `General`, `Filesystem`, `EXIF`, `IPTC`, `XMP`,
`Video`, `Audio`, `Office`, `PDF`, `Archives`, `Executable` et `Forensic`.
Elles n'impliquent aucune dépendance vers le PreviewPanel.

## Provider Images forensic

`ImageMetadataExtractor` (`pillow.image`) produit exclusivement des
`MetadataField` scalaires et persistables. Les valeurs numériques restent des
`int` ou `float`, les dates sont des `datetime` timezone-aware et les unités
restent séparées dans `MetadataField.unit`. Il n'effectue aucun accès Qt.

| Famille | Identifiants principaux |
|---|---|
| Général | `image.width`, `image.height`, `image.dimensions`, `image.color_mode`, `image.bits_per_pixel`, `image.format`, `image.dpi_x`, `image.dpi_y`, `image.gamma`, `image.compression` |
| EXIF | `exif.make`, `exif.model`, `exif.artist`, `exif.software`, `exif.orientation`, `exif.datetime_*`, `exif.lens_model`, `exif.focal_length`, `exif.f_number`, `exif.exposure_time`, `exif.iso`, `exif.flash`, `exif.white_balance`, `exif.exposure_mode`, `exif.metering_mode`, `exif.color_space` |
| GPS | `exif.gps.latitude`, `exif.gps.longitude`, `exif.gps.altitude`, `exif.gps.direction`, `exif.gps.speed`, `exif.gps.accuracy`, `exif.gps.timestamp` |
| IPTC | `iptc.keywords`, `iptc.author`, `iptc.caption`, `iptc.copyright`, `iptc.date_created` et les datasets non normalisés `iptc.<record>.<dataset>` |
| XMP | `xmp.<namespace>.<champ>` ; les espaces Adobe, Camera Raw et Lightroom utilisent notamment `xmp.xmp.*`, `xmp.crs.*` et `xmp.lightroom.*` |
| Formats | `png.text.*`, `png.ztxt.*`, `png.itxt.*`, `png.srgb`, `gif.*`, `webp.*`, `tiff.compression`, `bmp.compression` |
| Forensic | `image.icc_profile.sha256`, `image.icc_profile.size`, `exif.maker_note.sha256`, `exif.maker_note.size`, `exif.thumbnail.present`, `exif.thumbnail.sha256`, `exif.thumbnail.size` |

Les dates EXIF sans offset explicite sont enregistrées en UTC et accompagnées
du booléen `exif.datetime_*.timezone_assumed`. Les coordonnées GPS sont des
valeurs `float` décimales ; la vitesse est normalisée en km/h.

Pillow ne décode pas nativement tous les formats sur toutes les plateformes.
HEIC/HEIF et RAW (CR2, CR3, NEF, ARW, ORF, RW2, DNG) sont reconnus par
extension et sont analysés lorsqu'un décodeur Pillow est disponible dans le
runtime. Les MakerNotes sont conservées de manière sûre sous forme d'empreinte
et de taille ; leur décodage constructeur nécessite un provider spécialisé.

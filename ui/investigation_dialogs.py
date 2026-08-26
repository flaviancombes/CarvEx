"""Dialogues Qt de création Investigation, sans dépendance aux repositories."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QCompleter,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class EvidenceDialog(QDialog):
    """Formulaire UI d'une preuve ; les commandes restent dans le contrôleur."""

    def __init__(
        self,
        *,
        display_name: str,
        original_name: str,
        evidence_type: str,
        sha256: str,
        note: str,
        hypothesis: str,
        cases: tuple[tuple[str, str], ...],
        collections: tuple[tuple[str, str], ...],
        selected_case_id: str | None = None,
        selected_collection_id: str | None = None,
        already_present: bool = False,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ajouter cette preuve à Investigation")
        self.name_field = QLineEdit(display_name, self)
        self.original_name_field = self._readonly_field(original_name)
        self.type_field = self._readonly_field(evidence_type)
        self.sha256_field = self._readonly_field(sha256)
        self.note_field = QTextEdit(self)
        self.note_field.setPlainText(note)
        self.hypothesis_field = QLineEdit(hypothesis, self)
        self.case_field = self._choice_field(cases, "Aucune Case", selected_case_id)
        self.collection_field = self._choice_field(collections, "Aucune Collection", selected_collection_id)
        self.new_case_button = QPushButton("Nouvelle Case", self)
        self.new_collection_button = QPushButton("Nouvelle Collection", self)
        self.presence_label = QLabel("Cette preuve est déjà présente dans Investigation.", self)
        self.presence_label.setVisible(already_present)
        self.error_label = QLabel("", self)
        self.error_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok, self
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Enregistrer")
        self.buttons.rejected.connect(self.reject)
        self.buttons.accepted.connect(self._accept_if_valid)

        information = QFormLayout()
        information.addRow("Nom affiché *", self.name_field)
        information.addRow("Nom original", self.original_name_field)
        information.addRow("Type", self.type_field)
        information.addRow("SHA-256", self.sha256_field)
        context = QFormLayout()
        context.addRow("Note", self.note_field)
        context.addRow("Hypothèse", self.hypothesis_field)
        organization = QFormLayout()
        organization.addRow("Case existante", self.case_field)
        organization.addRow("", self.new_case_button)
        organization.addRow("Collection existante", self.collection_field)
        organization.addRow("", self.new_collection_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.presence_label)
        layout.addWidget(QLabel("Informations", self))
        layout.addLayout(information)
        layout.addWidget(QLabel("Contexte d'investigation", self))
        layout.addLayout(context)
        layout.addWidget(QLabel("Organisation", self))
        layout.addLayout(organization)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons)

    def _readonly_field(self, value: str) -> QLineEdit:
        field = QLineEdit(value, self)
        field.setReadOnly(True)
        return field

    def _choice_field(
        self,
        choices: tuple[tuple[str, str], ...],
        placeholder: str,
        selected_identifier: str | None,
    ) -> QComboBox:
        field = QComboBox(self)
        field.setEditable(True)
        field.addItem(placeholder, None)
        for label, identifier in choices:
            field.addItem(label, identifier)
        field.setCurrentIndex(max(0, field.findData(selected_identifier)))
        completer = field.completer()
        if isinstance(completer, QCompleter):
            completer.setFilterMode(Qt.MatchFlag.MatchContains)
            completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        return field

    def _accept_if_valid(self) -> None:
        if self.name_field.text().strip():
            self.accept()
            return
        self.error_label.setText("Le nom affiché de la preuve est requis.")
        self.name_field.setFocus()

    def add_case(self, title: str, identifier: str) -> None:
        """Insère la Case créée pendant l'édition et la sélectionne."""
        self.case_field.addItem(title, identifier)
        self.case_field.setCurrentIndex(self.case_field.findData(identifier))

    def add_collection(self, title: str, identifier: str) -> None:
        """Insère la Collection créée pendant l'édition et la sélectionne."""
        self.collection_field.addItem(title, identifier)
        self.collection_field.setCurrentIndex(self.collection_field.findData(identifier))


class _CreationDialog(QDialog):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.form = QFormLayout()
        self.error_label = QLabel("", self)
        self.error_label.setWordWrap(True)
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok, self
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Créer")
        self.buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addLayout(self.form)
        layout.addWidget(self.error_label)
        layout.addWidget(self.buttons)

    def show_validation_error(self, message: str, field) -> None:
        self.error_label.setText(message)
        field.setFocus()


class ItemCreationDialog(_CreationDialog):
    def __init__(self, parent=None) -> None:
        super().__init__("Créer un élément", parent)
        self.name_field = QLineEdit(self)
        self.description_field = QTextEdit(self)
        self.type_field = QLineEdit(self)
        self.form.addRow("Nom *", self.name_field)
        self.form.addRow("Description", self.description_field)
        self.form.addRow("Type", self.type_field)
        self.buttons.accepted.connect(self._accept_if_valid)

    def _accept_if_valid(self) -> None:
        if self.name_field.text().strip():
            self.accept()
        else:
            self.show_validation_error("Le nom de l'élément est requis.", self.name_field)


class NoteCreationDialog(_CreationDialog):
    def __init__(self, parent=None) -> None:
        super().__init__("Ajouter une note", parent)
        self.title_field = QLineEdit(self)
        self.body_field = QTextEdit(self)
        self.form.addRow("Titre", self.title_field)
        self.form.addRow("Contenu", self.body_field)
        self.buttons.accepted.connect(self._accept_if_valid)

    def _accept_if_valid(self) -> None:
        if self.body_field.toPlainText().strip():
            self.accept()
        else:
            self.show_validation_error("Le contenu de la note est requis.", self.body_field)


class HypothesisCreationDialog(_CreationDialog):
    def __init__(self, parent=None) -> None:
        super().__init__("Créer une hypothèse", parent)
        self.title_field = QLineEdit(self)
        self.description_field = QTextEdit(self)
        self.confidence_field = QComboBox(self)
        self.confidence_field.addItem("Faible", "low")
        self.confidence_field.addItem("Moyenne", "medium")
        self.confidence_field.addItem("Élevée", "high")
        self.status_field = QComboBox(self)
        self.status_field.addItem("Ouverte", "draft")
        self.status_field.addItem("En cours", "in_progress")
        self.status_field.addItem("Validée", "concluded")
        self.status_field.addItem("Rejetée", "archived")
        self.form.addRow("Titre", self.title_field)
        self.form.addRow("Description", self.description_field)
        self.form.addRow("Confiance", self.confidence_field)
        self.form.addRow("Statut", self.status_field)
        self.buttons.accepted.connect(self._accept_if_valid)

    def _accept_if_valid(self) -> None:
        if self.title_field.text().strip():
            self.accept()
        else:
            self.show_validation_error("Le titre de l'hypothèse est requis.", self.title_field)


class CaseCreationDialog(_CreationDialog):
    def __init__(self, parent=None) -> None:
        super().__init__("Créer un dossier (Case)", parent)
        self.name_field = QLineEdit(self)
        self.description_field = QTextEdit(self)
        self.form.addRow("Nom", self.name_field)
        self.form.addRow("Description", self.description_field)
        self.buttons.accepted.connect(self._accept_if_valid)

    def _accept_if_valid(self) -> None:
        if self.name_field.text().strip():
            self.accept()
        else:
            self.show_validation_error("Le nom de la Case est requis.", self.name_field)


class CollectionCreationDialog(_CreationDialog):
    def __init__(self, parent=None) -> None:
        super().__init__("Créer une collection", parent)
        self.name_field = QLineEdit(self)
        self.description_field = QTextEdit(self)
        self.form.addRow("Nom", self.name_field)
        self.form.addRow("Description", self.description_field)
        self.buttons.accepted.connect(self._accept_if_valid)

    def _accept_if_valid(self) -> None:
        if self.name_field.text().strip():
            self.accept()
        else:
            self.show_validation_error("Le nom de la collection est requis.", self.name_field)


class RelationCreationDialog(_CreationDialog):
    """Dialogue Qt recevant des références déjà résolues par le contrôleur."""

    def __init__(self, targets, relation_types, parent=None) -> None:
        super().__init__("Créer une relation", parent)
        self.source_field = QComboBox(self)
        self.relation_type_field = QComboBox(self)
        self.destination_field = QComboBox(self)
        for label, kind, identifier in targets:
            data = (kind, identifier)
            self.source_field.addItem(label, data)
            self.destination_field.addItem(label, data)
        for label, value in relation_types:
            self.relation_type_field.addItem(label, value)
        self.form.addRow("Objet source", self.source_field)
        self.form.addRow("Type de relation", self.relation_type_field)
        self.form.addRow("Objet cible", self.destination_field)
        self.buttons.accepted.connect(self._accept_if_valid)

    def _accept_if_valid(self) -> None:
        if self.source_field.count() >= 2 and self.destination_field.count() >= 2 and self.relation_type_field.count():
            self.accept()
        else:
            self.show_validation_error("Au moins deux objets Investigation sont requis.", self.source_field)


class MembershipSelectionDialog(_CreationDialog):
    """Choisit un conteneur existant, sans jamais exposer le repository à Qt."""

    def __init__(self, title: str, label: str, choices, parent=None) -> None:
        super().__init__(title, parent)
        self.container_field = QComboBox(self)
        for display_name, identifier in choices:
            self.container_field.addItem(display_name, identifier)
        self.form.addRow(label, self.container_field)
        self.buttons.accepted.connect(self._accept_if_valid)

    def _accept_if_valid(self) -> None:
        if self.container_field.count():
            self.accept()
        else:
            self.show_validation_error("Aucun conteneur disponible.", self.container_field)

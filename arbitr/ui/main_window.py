from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from arbitr.models import GenerationConfig, RunResult
from arbitr.orchestrator import ArbitrationOrchestrator
from arbitr.providers.base import LLMProvider
from arbitr.providers.registry import default_providers
from arbitr.storage import Storage


class WorkerSignals(QObject):
    finished = Signal(object)
    failed = Signal(str)
    progress = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Arbitr")
        self.resize(1320, 880)

        self.storage = Storage(Path("arbitr_history.db"))
        self.providers = default_providers()
        self.provider_checks: list[QCheckBox] = []

        self.history_list = QListWidget()
        self.history_list.itemSelectionChanged.connect(self.on_history_selected)

        self.tabs = QTabWidget()
        self.userchat_tab = self._build_userchat_tab()
        self.arbitration_tab = self._build_arbitration_tab()
        self.protocol_tab = self._build_protocol_tab()
        self.settings_tab = self._build_settings_tab()
        self.logs_tab = self._build_logs_tab()

        self.tabs.addTab(self.userchat_tab, "UserChat")
        self.tabs.addTab(self.arbitration_tab, "Арбитраж")
        self.tabs.addTab(self.protocol_tab, "Протокол")
        self.tabs.addTab(self.settings_tab, "Настройки")
        self.tabs.addTab(self.logs_tab, "Логи")

        root = QWidget()
        layout = QHBoxLayout(root)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.addWidget(QLabel("История диалогов и веток размышления"))
        left_layout.addWidget(self.history_list)

        layout.addWidget(left_panel, 2)
        layout.addWidget(self.tabs, 8)

        self.setCentralWidget(root)

        self.signals = WorkerSignals()
        self.signals.finished.connect(self.on_finished)
        self.signals.failed.connect(self.on_failed)
        self.signals.progress.connect(self.on_progress)

        self._append_log("Приложение запущено")
        self.refresh_history()

    def _build_userchat_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Окно ввода вопроса"))
        self.query_edit = QPlainTextEdit()
        self.query_edit.setPlaceholderText("Введите вопрос...")
        layout.addWidget(self.query_edit)

        self.send_button = QPushButton("Отправить")
        self.send_button.clicked.connect(self.on_run)
        layout.addWidget(self.send_button)
        return tab

    def _build_arbitration_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Индикатор этапов пайплайна"))
        self.stage_indicator = QLabel("Ожидание")
        layout.addWidget(self.stage_indicator)

        layout.addWidget(QLabel("Чат + финальный ответ"))
        self.final_output_view = QPlainTextEdit()
        self.final_output_view.setReadOnly(True)
        layout.addWidget(self.final_output_view)
        return tab

    def _build_protocol_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.addWidget(QLabel("Stage 1 ответы"))
        self.protocol_stage1 = QPlainTextEdit()
        self.protocol_stage1.setReadOnly(True)
        layout.addWidget(self.protocol_stage1)

        layout.addWidget(QLabel("Stage 2 оценки"))
        self.protocol_stage2 = QPlainTextEdit()
        self.protocol_stage2.setReadOnly(True)
        layout.addWidget(self.protocol_stage2)

        layout.addWidget(QLabel("Итоговый рейтинг"))
        self.protocol_aggregation = QPlainTextEdit()
        self.protocol_aggregation.setReadOnly(True)
        layout.addWidget(self.protocol_aggregation)
        return tab

    def _build_settings_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        layout.addWidget(QLabel("Активные модели (Stage 1/2)"))
        for provider in self.providers:
            cb = QCheckBox(provider.name)
            cb.setChecked(True)
            self.provider_checks.append(cb)
            layout.addWidget(cb)

        layout.addWidget(QLabel("Chairman"))
        self.chairman_combo = QComboBox()
        self.chairman_combo.addItems([p.name for p in self.providers])
        layout.addWidget(self.chairman_combo)

        layout.addWidget(QLabel("temperature"))
        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(0.3)
        layout.addWidget(self.temperature_spin)

        layout.addWidget(QLabel("max tokens"))
        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(64, 32000)
        self.max_tokens_spin.setValue(1200)
        layout.addWidget(self.max_tokens_spin)

        layout.addWidget(QLabel("timeout (seconds)"))
        self.timeout_spin = QDoubleSpinBox()
        self.timeout_spin.setRange(5.0, 600.0)
        self.timeout_spin.setValue(60.0)
        layout.addWidget(self.timeout_spin)

        layout.addStretch(1)
        return tab

    def _build_logs_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.logs_view = QPlainTextEdit()
        self.logs_view.setReadOnly(True)
        layout.addWidget(self.logs_view)
        return tab

    def selected_providers(self) -> list[LLMProvider]:
        result = []
        for provider, check in zip(self.providers, self.provider_checks):
            if check.isChecked():
                result.append(provider)
        return result

    def selected_chairman(self) -> LLMProvider:
        name = self.chairman_combo.currentText()
        for provider in self.providers:
            if provider.name == name:
                return provider
        return self.providers[0]

    def build_generation_config(self) -> GenerationConfig:
        return GenerationConfig(
            temperature=self.temperature_spin.value(),
            max_tokens=self.max_tokens_spin.value(),
            timeout_s=self.timeout_spin.value(),
        )

    def on_run(self) -> None:
        query = self.query_edit.toPlainText().strip()
        if not query:
            QMessageBox.warning(self, "Arbitr", "Введите вопрос")
            return

        providers = self.selected_providers()
        if len(providers) < 2:
            QMessageBox.warning(self, "Arbitr", "Выберите минимум 2 модели")
            return

        chairman = self.selected_chairman()
        config = self.build_generation_config()

        self.send_button.setEnabled(False)
        self.stage_indicator.setText("Запуск...")
        self.final_output_view.setPlainText("Выполняется арбитраж...")
        self.tabs.setCurrentWidget(self.arbitration_tab)
        self._append_log(
            f"Запуск: providers={len(providers)}, chairman={chairman.name}, "
            f"temperature={config.temperature}, max_tokens={config.max_tokens}, timeout={config.timeout_s}"
        )

        def _runner() -> None:
            try:
                orchestrator = ArbitrationOrchestrator(providers=providers, chairman=chairman, config=config)
                run = asyncio.run(orchestrator.run(query, on_progress=self.signals.progress.emit))
                self.storage.save_run(run)
                self.signals.finished.emit(run)
            except Exception as exc:
                self.signals.failed.emit(str(exc))

        threading.Thread(target=_runner, daemon=True).start()

    def on_progress(self, message: str) -> None:
        self.stage_indicator.setText(message)
        self._append_log(message)

    def on_finished(self, run: RunResult) -> None:
        self.send_button.setEnabled(True)
        self.stage_indicator.setText("Готово")

        self.final_output_view.setPlainText(run.final_answer)
        self.protocol_stage1.setPlainText(
            "\n\n".join([
                f"[{item.model_name}]\n{item.content or ('ERROR: ' + (item.error or ''))}" for item in run.stage1
            ])
        )
        self.protocol_stage2.setPlainText(
            "\n\n".join([
                f"[{review.reviewer}]\n{review.analysis}\n\nRanking: {', '.join(review.ranking) if review.ranking else 'n/a'}"
                for review in run.stage2
            ])
        )

        if run.aggregated:
            aggregation_text = "\n".join([
                f"{label}: {run.aggregated.scores[label]:.2f}" for label in run.aggregated.ranking
            ])
        else:
            aggregation_text = "Нет данных"
        self.protocol_aggregation.setPlainText(aggregation_text)

        self._append_log("Арбитраж завершен успешно")
        self.refresh_history()
        self.tabs.setCurrentWidget(self.protocol_tab)

    def on_failed(self, error: str) -> None:
        self.send_button.setEnabled(True)
        self.stage_indicator.setText("Ошибка")
        self._append_log(f"Ошибка: {error}")
        QMessageBox.critical(self, "Arbitr", f"Сбой пайплайна: {error}")

    def refresh_history(self) -> None:
        self.history_list.clear()
        for row in self.storage.list_runs():
            self.history_list.addItem(f"#{row['id']} {row['title']}")

    def on_history_selected(self) -> None:
        selected = self.history_list.currentItem()
        if not selected:
            return
        run_id = int(selected.text().split()[0][1:])
        row = self.storage.get_run(run_id)
        if not row:
            return
        self.query_edit.setPlainText(row["user_query"])
        self.final_output_view.setPlainText(row["final_answer"])

        stage1_text = "\n\n".join([
            f"[{item['model_name']}]\n{item.get('content') or ('ERROR: ' + (item.get('error') or ''))}"
            for item in row["stage1"]
        ])
        stage2_text = "\n\n".join([
            f"[{item['reviewer']}]\n{item['analysis']}\n\nRanking: {', '.join(item.get('ranking') or []) or 'n/a'}"
            for item in row["stage2"]
        ])
        aggregation = row["aggregation"]
        ranking = aggregation.get("ranking") or []
        scores = aggregation.get("scores") or {}
        aggregation_text = "\n".join([f"{label}: {scores.get(label, 0):.2f}" for label in ranking]) if ranking else "Нет данных"

        self.protocol_stage1.setPlainText(stage1_text)
        self.protocol_stage2.setPlainText(stage2_text)
        self.protocol_aggregation.setPlainText(aggregation_text)

    def _append_log(self, message: str) -> None:
        existing = self.logs_view.toPlainText().strip()
        if existing:
            self.logs_view.setPlainText(f"{existing}\n{message}")
        else:
            self.logs_view.setPlainText(message)

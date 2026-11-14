#include "mainwindow.h"

#include "chartbrowser.h"
#include "graphview.h"
#include "sourceview.h"

#include <QAction>
#include <QDockWidget>
#include <QFileInfo>
#include <QLabel>
#include <QPlainTextEdit>

namespace flowcharts {

void MainWindow::openPaths(const QStringList &paths) {
    QStringList absolutePaths;
    for (const auto &path : paths)
        absolutePaths.append(QFileInfo(path).absoluteFilePath());
    m_paths = absolutePaths;
    m_workspace = Workspace{};
    m_browser->setWorkspace(m_workspace);
    m_source->clear();
    m_diagnostics->clear();
    m_graph->clearGraph("Analysing source files…");
    m_history.clear();
    m_historyIndex = -1;
    m_hasChart = false;
    m_graphRequest = -1;
    m_refreshRequest = -1;
    m_back->setEnabled(false);
    m_forward->setEnabled(false);
    m_openRequest = m_engine.request("open", {{"paths", QJsonArray::fromStringList(m_paths)}});
}

void MainWindow::acceptResult(qint64 id, const QString &method, const QJsonObject &result) {
    if (method == "open") {
        if (id == m_openRequest)
            applySnapshot(result["snapshot"].toObject());
    } else if (method == "refresh") {
        if (id == m_refreshRequest && result["changed"].toBool())
            applySnapshot(result["snapshot"].toObject());
    } else if (method == "graph" && id == m_graphRequest) {
        if (result["generation"].toInt() != m_workspace.generation())
            return;
        GraphLayout graph;
        QString error;
        if (!parseLayout(result["layout"].toObject(), graph, error)) {
            m_graph->clearGraph(error);
            reportError(error);
            return;
        }
        m_graph->setGraph(graph, m_workspace.key(m_current));
    }
}

void MainWindow::applySnapshot(const QJsonObject &snapshot) {
    const auto previousSource = m_workspace.sourcePath(m_current.document);
    const auto previousName = m_current.qualname;
    // History refers to document indexes. Remap it through stable file/chart identities.
    QVector<QPair<QString, QString>> history;
    for (const auto &ref : m_history)
        history.append({m_workspace.sourcePath(ref.document), ref.qualname});
    QString error;
    if (!m_workspace.setSnapshot(snapshot, error)) {
        reportError(error);
        return;
    }
    m_browser->setWorkspace(m_workspace);
    const auto diagnostics = m_workspace.diagnostics();
    m_diagnostics->setPlainText(diagnostics.join('\n'));
    if (!diagnostics.isEmpty())
        m_diagnosticsDock->show();
    for (int i = 0; i < history.size(); ++i)
        m_history[i] =
            m_workspace.findChart(history[i].first, history[i].second).value_or(ChartRef{});
    const auto ref = m_workspace.findChart(previousSource, previousName).value_or(ChartRef{});
    showChart(ref, m_history.isEmpty());
    if (m_current.document < 0)
        setWindowTitle("Call graph — Flowcharts");
}

void MainWindow::showChart(const ChartRef &ref, bool record) {
    if (m_workspace.generation() == 0)
        return;
    if (ref.document >= 0 && m_workspace.chart(ref).isEmpty())
        return;
    const bool same = m_hasChart && m_graph->chartKey() == m_workspace.key(ref);
    m_current = ref;
    m_hasChart = true;
    m_browser->selectChart(ref);
    if (record && (m_historyIndex < 0 || !(m_history[m_historyIndex] == ref))) {
        m_history.resize(m_historyIndex + 1);
        m_history.append(ref);
        m_historyIndex = m_history.size() - 1;
    }
    m_back->setEnabled(m_historyIndex > 0);
    m_forward->setEnabled(m_historyIndex + 1 < m_history.size());
    m_selection->clear();
    if (ref.document < 0) {
        m_source->clear();
        setWindowTitle("Call graph — Flowcharts");
    } else {
        const auto text = m_workspace.sourceText(ref.document);
        if (m_source->toPlainText() != text)
            m_source->setPlainText(text);
        m_source->highlightLines(0, 0);
        setWindowTitle(ref.qualname + " — " + m_workspace.sourcePath(ref.document) +
                       " — Flowcharts");
    }
    if (!same)
        m_graph->clearGraph("Laying out graph…");
    QJsonObject params{
        {"generation", m_workspace.generation()},
        {"document", ref.document < 0 ? QJsonValue::Null : QJsonValue(ref.document)}};
    if (ref.document >= 0)
        params["qualname"] = ref.qualname;
    m_graphRequest = m_engine.request("graph", params);
}

void MainWindow::showFile(int document, const QString &message, int line) {
    m_hasChart = false;
    m_graphRequest = -1;
    m_graph->clearGraph(message.isEmpty() ? "Choose a function or the module chart" : message);
    m_source->setPlainText(m_workspace.sourceText(document));
    m_source->highlightLines(line, line);
    m_selection->clear();
    setWindowTitle("Flowcharts");
}

void MainWindow::selectNode(const QString &id) {
    if (!m_hasChart)
        return;
    const auto node = m_workspace.node(m_current, id);
    const auto location = node["location"].toObject();
    m_source->highlightLines(location["line"].toInt(), location["end_line"].toInt());
    QStringList calls;
    for (const auto &value : m_workspace.chart(m_current)["calls"].toArray()) {
        const auto call = value.toObject();
        if (call["node"].toString() == id)
            calls.append(call["text"].toString());
    }
    const bool navigable = m_workspace.target(m_current, id).has_value();
    m_selection->setText(id.isEmpty()
                             ? QString{}
                             : node["label"].toString().section('\n', 0, 0) +
                                   (calls.isEmpty() ? "" : " · Calls: " + calls.join(", ")) +
                                   (navigable ? " · Double-click to open" : ""));
}

void MainWindow::navigate(int delta) {
    const int next = m_historyIndex + delta;
    if (next < 0 || next >= m_history.size())
        return;
    m_historyIndex = next;
    showChart(m_history[next], false);
}

} // namespace flowcharts

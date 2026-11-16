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
    m_history.refs.clear();
    m_history.index = -1;
    m_hasChart = false;
    m_file.reset();
    m_requests.graph = -1;
    m_requests.refresh = -1;
    m_requests.refreshError.clear();
    m_back->setEnabled(false);
    m_forward->setEnabled(false);
    m_requests.open = m_engine.request("open", {{"paths", QJsonArray::fromStringList(m_paths)}});
}

void MainWindow::acceptResult(qint64 id, const QString &method, const QJsonObject &result) {
    if (method == "open") {
        if (id == m_requests.open)
            applySnapshot(result["snapshot"].toObject());
    } else if (method == "refresh") {
        if (id != m_requests.refresh)
            return;
        m_requests.refreshError.clear();
        if (result["changed"].toBool())
            applySnapshot(result["snapshot"].toObject());
    } else if (method == "graph" && id == m_requests.graph) {
        if (result["generation"].toInt() != m_workspace.generation())
            return;
        GraphLayout graph;
        if (QString error; !parseLayout(result["layout"].toObject(), graph, error)) {
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
    for (const auto &ref : m_history.refs)
        history.append({m_workspace.sourcePath(ref.document), ref.qualname});
    if (QString error; !m_workspace.setSnapshot(snapshot, error)) {
        reportError(error);
        return;
    }
    m_browser->setWorkspace(m_workspace);
    const auto diagnostics = m_workspace.diagnostics();
    m_diagnostics->setPlainText(diagnostics.join('\n'));
    m_diagnosticsDock->setVisible(!diagnostics.isEmpty());
    const int oldIndex = m_history.index;
    m_history.refs.clear();
    m_history.index = -1;
    for (int i = 0; i < history.size(); ++i) {
        const auto ref = history[i].first.isEmpty()
                             ? std::optional<ChartRef>{ChartRef{}}
                             : m_workspace.findChart(history[i].first, history[i].second);
        if (!ref)
            continue;
        m_history.refs.append(*ref);
        if (i <= oldIndex)
            m_history.index = m_history.refs.size() - 1;
    }
    m_back->setEnabled(m_history.index > 0);
    m_forward->setEnabled(m_history.index + 1 < m_history.refs.size());
    if (m_file) {
        showFile(*m_file);
        return;
    }
    const auto ref = previousSource.isEmpty() ? std::optional<ChartRef>{ChartRef{}}
                                              : m_workspace.findChart(previousSource, previousName);
    const auto fallback = m_history.index >= 0 ? m_history.refs[m_history.index] : ChartRef{};
    showChart(ref.value_or(fallback), m_history.refs.isEmpty());
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
    m_file.reset();
    m_hasChart = true;
    m_browser->selectChart(ref);
    if (record && (m_history.index < 0 || !(m_history.refs[m_history.index] == ref))) {
        m_history.refs.resize(m_history.index + 1);
        m_history.refs.append(ref);
        m_history.index = m_history.refs.size() - 1;
    }
    m_back->setEnabled(m_history.index > 0);
    m_forward->setEnabled(m_history.index + 1 < m_history.refs.size());
    m_selection->clear();
    if (ref.document < 0) {
        m_source->clear();
        setWindowTitle("Call graph — Flowcharts");
    } else {
        if (const auto text = m_workspace.sourceText(ref.document); m_source->toPlainText() != text)
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
    m_requests.graph = m_engine.request("graph", params);
}

void MainWindow::showFile(FileRef ref) {
    m_file = ref;
    m_hasChart = false;
    m_requests.graph = -1;
    const auto view = m_workspace.fileView(ref).value_or(
        FileView{-1, "Source file is no longer in the workspace", 0});
    m_browser->selectFile(ref);
    m_graph->clearGraph(view.message.isEmpty() ? "Choose a function or the module chart"
                                               : view.message);
    m_source->setPlainText(m_workspace.sourceText(view.document));
    m_source->highlightLines(view.line, view.line);
    m_selection->clear();
    setWindowTitle(ref.source + " — Flowcharts");
}

void MainWindow::selectNode(const QString &id) {
    if (!m_hasChart)
        return;
    const auto location = m_workspace.node(m_current, id)["location"].toObject();
    m_source->highlightLines(location["line"].toInt(), location["end_line"].toInt());
    if (id.isEmpty()) {
        m_selection->clear();
        return;
    }
    QStringList calls;
    for (const auto &value : m_workspace.chart(m_current)["calls"].toArray()) {
        const auto call = value.toObject();
        if (call["node"].toString() == id)
            calls.append(call["text"].toString());
    }
    QString text = m_workspace.nodeTitle(m_current, id);
    if (!calls.isEmpty())
        text += " · Calls: " + calls.join(", ");
    if (m_workspace.target(m_current, id))
        text += " · Double-click to open";
    m_selection->setText(text);
}

void MainWindow::navigate(int delta) {
    const int next = m_history.index + delta;
    if (next < 0 || next >= m_history.refs.size())
        return;
    m_history.index = next;
    showChart(m_history.refs[next], false);
}

} // namespace flowcharts

#pragma once

#include "engineclient.h"
#include "workspace.h"

#include <QMainWindow>

class QAction;
class QDockWidget;
class QLabel;
class QPlainTextEdit;

namespace flowcharts {

class ChartBrowser;
class GraphView;
class SourceView;

class MainWindow : public QMainWindow {
    Q_OBJECT
public:
    MainWindow(const QString &engine, const QStringList &arguments, QWidget *parent = nullptr);
    void openPaths(const QStringList &paths);

private:
    void buildActions();
    void restartEngine();
    void acceptResult(qint64 id, const QString &method, const QJsonObject &result);
    void applySnapshot(const QJsonObject &snapshot);
    void showChart(const ChartRef &ref, bool record = true);
    void showFile(int document, const QString &message, int line);
    void selectNode(const QString &id);
    void navigate(int delta);
    void reportError(const QString &message);

    EngineClient m_engine;
    QString m_program;
    QStringList m_arguments;
    QStringList m_paths;
    Workspace m_workspace;
    ChartRef m_current;
    bool m_hasChart = false;
    qint64 m_openRequest = -1;
    qint64 m_graphRequest = -1;
    qint64 m_refreshRequest = -1;
    QVector<ChartRef> m_history;
    int m_historyIndex = -1;
    ChartBrowser *m_browser;
    GraphView *m_graph;
    SourceView *m_source;
    QPlainTextEdit *m_diagnostics;
    QDockWidget *m_sourceDock;
    QDockWidget *m_diagnosticsDock;
    QLabel *m_status;
    QLabel *m_selection;
    QAction *m_back = nullptr;
    QAction *m_forward = nullptr;
};

} // namespace flowcharts

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
    void connectViews();
    void connectEngine();
    void engineFailed(qint64 id, const QString &method, const QString &message);
    void restartEngine();
    void acceptResult(qint64 id, const QString &method, const QJsonObject &result);
    void applySnapshot(const QJsonObject &snapshot);
    void showChart(const ChartRef &ref, bool record = true);
    void showFile(FileRef ref);
    void selectNode(const QString &id);
    void navigate(int delta);
    void reportError(const QString &message);

    EngineClient m_engine;
    QString m_program;
    QStringList m_arguments;
    QStringList m_paths;
    Workspace m_workspace;
    ChartRef m_current;
    std::optional<FileRef> m_file;
    bool m_hasChart = false;
    // The latest request of each kind; answers to older ones are ignored.
    struct Requests {
        qint64 open = -1;
        qint64 graph = -1;
        qint64 refresh = -1;
        QString refreshError; // Reported once until a refresh succeeds or another error occurs.
    };
    Requests m_requests;
    struct History {
        QVector<ChartRef> refs;
        int index = -1;
    };
    History m_history;
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

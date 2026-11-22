#include "mainwindow.h"

#include "chartbrowser.h"
#include "graphview.h"
#include "sourceview.h"

#include <QAction>
#include <QDockWidget>
#include <QFileDialog>
#include <QLabel>
#include <QMenuBar>
#include <QPlainTextEdit>
#include <QStatusBar>
#include <QToolBar>

namespace flowcharts {

MainWindow::MainWindow(const QString &engine, const QStringList &arguments,
                       const QString &workingDirectory, QWidget *parent)
    : QMainWindow(parent), m_program(engine), m_arguments(arguments),
      m_workingDirectory(workingDirectory), m_browser(new ChartBrowser(this)),
      m_graph(new GraphView(this)), m_source(new SourceView(this)),
      m_diagnostics(new QPlainTextEdit(this)), m_sourceDock(new QDockWidget("Source", this)),
      m_diagnosticsDock(new QDockWidget("Diagnostics", this)),
      m_status(new QLabel("Starting engine…", this)), m_selection(new QLabel(this)) {
    setWindowTitle("Flowcharts");
    resize(1500, 900);
    setDockNestingEnabled(true);
    setCentralWidget(m_graph);
    auto *browserDock = new QDockWidget("Workspace", this);
    browserDock->setWidget(m_browser);
    browserDock->setObjectName("workspaceDock");
    addDockWidget(Qt::LeftDockWidgetArea, browserDock);
    m_sourceDock->setWidget(m_source);
    m_sourceDock->setObjectName("sourceDock");
    addDockWidget(Qt::RightDockWidgetArea, m_sourceDock);
    m_diagnostics->setReadOnly(true);
    m_diagnosticsDock->setWidget(m_diagnostics);
    m_diagnosticsDock->setObjectName("diagnosticsDock");
    addDockWidget(Qt::BottomDockWidgetArea, m_diagnosticsDock);
    m_diagnosticsDock->hide();
    resizeDocks({browserDock, m_sourceDock}, {270, 450}, Qt::Horizontal);
    statusBar()->addWidget(m_selection, 1);
    m_status->setObjectName("engineStatus");
    statusBar()->addPermanentWidget(m_status);
    buildActions();
    menuBar()->findChild<QMenu *>("viewMenu")->addAction(browserDock->toggleViewAction());
    connectViews();
    connectEngine();
    m_engine.start(m_program, m_arguments, m_workingDirectory);
}

void MainWindow::connectViews() {
    connect(m_browser, &ChartBrowser::chartSelected, this,
            [this](int doc, const QString &name) { showChart({doc, name}); });
    connect(m_browser, &ChartBrowser::fileSelected, this,
            [this](const QString &source, const QString &name) { showFile({source, name}); });
    connect(m_graph, &GraphView::nodeSelected, this, &MainWindow::selectNode);
    connect(m_graph, &GraphView::nodeActivated, this, [this](const QString &id) {
        if (auto target = m_workspace.target(m_current, id))
            showChart(*target);
    });
    connect(m_source, &SourceView::lineClicked, this, [this](int line) {
        if (m_hasChart && m_current.document >= 0)
            m_graph->selectNode(m_workspace.nodeForLine(m_current, line));
    });
}

void MainWindow::connectEngine() {
    connect(&m_engine, &EngineClient::succeeded, this, &MainWindow::acceptResult);
    connect(&m_engine, &EngineClient::failed, this,
            [this](qint64 id, const QString &method, const QString &, const QString &message) {
                engineFailed(id, method, message);
            });
    connect(&m_engine, &EngineClient::fatalError, this, [this](const QString &message) {
        m_status->setText("Engine disconnected");
        reportError(message);
    });
    // The background refresh poll runs every second and usually answers at once; only work
    // that takes noticeable time shows "Working…", so the status does not flicker.
    auto *busyDelay = new QTimer(this);
    busyDelay->setSingleShot(true);
    busyDelay->setInterval(500);
    connect(busyDelay, &QTimer::timeout, this, [this] {
        if (m_engine.running())
            m_status->setText("Working…");
    });
    connect(&m_engine, &EngineClient::busyChanged, this, [this, busyDelay](bool busy) {
        if (busy) {
            if (!busyDelay->isActive())
                busyDelay->start();
            return;
        }
        busyDelay->stop();
        if (m_engine.running())
            m_status->setText("Ready");
    });
    auto *poll = new QTimer(this);
    poll->setInterval(1000);
    connect(poll, &QTimer::timeout, this, [this] {
        if (m_workspace.generation() > 0 && m_engine.idle())
            m_requests.refresh = m_engine.request("refresh", {});
    });
    poll->start();
}

void MainWindow::engineFailed(qint64 id, const QString &method, const QString &message) {
    if ((method == "graph" && id != m_requests.graph) ||
        (method == "open" && id != m_requests.open) ||
        (method == "refresh" && id != m_requests.refresh))
        return;
    if (method == "refresh") {
        // The poll retries every second; a lasting failure is reported once.
        if (message == m_requests.refreshError)
            return;
        m_requests.refreshError = message;
    }
    if (method == "graph" || method == "open")
        m_graph->clearGraph(message);
    reportError(message);
}

void MainWindow::buildActions() {
    auto *file = menuBar()->addMenu("&File");
    auto *toolbar = addToolBar("Navigation");
    toolbar->setObjectName("navigationToolbar");
    auto *open = file->addAction("Open &files…", this, [this] {
        const auto paths = QFileDialog::getOpenFileNames(this, "Open source files", {},
                                                         "Source files (*.py);;All files (*)");
        if (!paths.isEmpty())
            openPaths(paths);
    });
    open->setShortcut(QKeySequence::Open);
    toolbar->addAction(open);
    file->addAction("Open &folder…", this, [this] {
        const auto path = QFileDialog::getExistingDirectory(this, "Open source folder");
        if (!path.isEmpty())
            openPaths({path});
    });
    auto *reload = file->addAction("&Reload", this, [this] {
        if (!m_paths.isEmpty())
            openPaths(m_paths);
    });
    reload->setShortcut(QKeySequence::Refresh);
    file->addAction("Restart analysis &engine", this, &MainWindow::restartEngine);
    file->addSeparator();
    file->addAction("&Quit", QKeySequence::Quit, this, &QWidget::close);
    toolbar->addSeparator();
    m_back = toolbar->addAction("Back", this, [this] { navigate(-1); });
    m_back->setShortcut(QKeySequence::Back);
    m_forward = toolbar->addAction("Forward", this, [this] { navigate(1); });
    m_forward->setShortcut(QKeySequence::Forward);
    m_back->setEnabled(false);
    m_forward->setEnabled(false);
    toolbar->addAction("Call graph", this, [this] { showChart({}); });
    toolbar->addSeparator();
    auto *view = menuBar()->addMenu("&View");
    view->setObjectName("viewMenu");
    auto *fit = view->addAction("&Fit graph", m_graph, &GraphView::fitGraph);
    fit->setShortcut(QKeySequence("Ctrl+0"));
    toolbar->addAction(fit);
    auto *zoomIn = view->addAction("Zoom &in", this, [this] { m_graph->zoom(1.25); });
    zoomIn->setShortcut(QKeySequence::ZoomIn);
    auto *zoomOut = view->addAction("Zoom &out", this, [this] { m_graph->zoom(0.8); });
    zoomOut->setShortcut(QKeySequence::ZoomOut);
    view->addSeparator();
    view->addAction(m_sourceDock->toggleViewAction());
    view->addAction(m_diagnosticsDock->toggleViewAction());
    auto *search = view->addAction("&Search charts", m_browser, &ChartBrowser::focusSearch);
    search->setShortcut(QKeySequence::Find);
}

void MainWindow::restartEngine() {
    m_workspace = Workspace{};
    m_engine.start(m_program, m_arguments, m_workingDirectory);
    if (!m_paths.isEmpty())
        openPaths(m_paths);
}

void MainWindow::reportError(const QString &message) {
    m_diagnostics->appendPlainText(message);
    m_diagnosticsDock->show();
    statusBar()->showMessage(message.section('\n', 0, 0), 10000);
}

} // namespace flowcharts

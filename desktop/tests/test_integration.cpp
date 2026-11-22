#include "chartbrowser.h"
#include "commandline.h"
#include "graphview.h"
#include "mainwindow.h"
#include "sourceview.h"

#include <QAction>
#include <QDir>
#include <QFile>
#include <QGraphicsItem>
#include <QGraphicsScene>
#include <QSignalSpy>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QTreeView>
#include <QtTest>

#include <algorithm>

using namespace flowcharts;

static bool hasNode(const GraphView *view, const QString &prefix) {
    const auto items = view->scene()->items();
    return std::any_of(items.cbegin(), items.cend(), [&prefix](const QGraphicsItem *item) {
        return item->data(0).toString().startsWith(prefix);
    });
}

static void writeSource(const QString &path, const QByteArray &text) {
    QFile file(path);
    QVERIFY(file.open(QIODevice::WriteOnly));
    QCOMPARE(file.write(text), text.size());
}

// The launcher's own default: the real Python worker from this checkout.
static LaunchOptions defaultEngine() {
    QCommandLineParser parser;
    configureCommandLine(parser);
    parser.process(QStringList{"flowcharts-desktop"});
    return launchOptions(parser, FLOWCHARTS_PROJECT_DIR);
}

// Restores the current directory when a test that changes it returns or fails.
struct CurrentDirectory {
    QString previous = QDir::currentPath();
    CurrentDirectory() = default;
    CurrentDirectory(const CurrentDirectory &) = delete;
    CurrentDirectory &operator=(const CurrentDirectory &) = delete;
    ~CurrentDirectory() { QDir::setCurrent(previous); }
};

class IntegrationTest : public QObject {
    Q_OBJECT
private slots:
    void fileViewSurvivesRefresh_data() {
        QTest::addColumn<bool>("skipped");
        QTest::addColumn<bool>("previousChart");
        QTest::newRow("file-after-chart") << false << true;
        QTest::newRow("file-after-callgraph") << false << false;
        QTest::newRow("skipped-after-chart") << true << true;
        QTest::newRow("skipped-after-callgraph") << true << false;
    }
    void fileViewSurvivesRefresh() {
        QFETCH(bool, skipped);
        QFETCH(bool, previousChart);
        const auto uv = QStandardPaths::findExecutable("uv");
        if (uv.isEmpty())
            QSKIP("uv is needed for the real Python worker integration test");
        QTemporaryDir directory;
        QVERIFY(directory.isValid());
        writeSource(directory.filePath("previous.py"), "def previous():\n    pass\n");
        const auto path = directory.filePath("z.py");
        const QByteArray text = "def selected():\n    pass\n\ndef broken():\n    break\n";
        writeSource(path, text);
        const auto engine = defaultEngine();
        MainWindow window(engine.program, engine.arguments, engine.workingDirectory);
        window.show();
        window.openPaths({directory.path()});
        auto *graph = window.findChild<GraphView *>();
        auto *source = window.findChild<SourceView *>();
        auto *browser = window.findChild<ChartBrowser *>();
        auto *tree = browser->findChild<QTreeView *>();
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "0#previous"), 15000);
        if (previousChart) {
            browser->chartSelected(0, "previous");
            QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "previous#start"), 10000);
        }
        auto file = tree->model()->index(2, 0);
        QCOMPARE(QDir::fromNativeSeparators(file.data(Qt::ToolTipRole).toString()), path);
        auto selected = skipped ? tree->model()->index(1, 0, file) : file;
        QVERIFY(selected.isValid());
        const auto selectedLabel = selected.data().toString();
        tree->setCurrentIndex(selected);
        QCOMPARE(source->toPlainText(), QString::fromUtf8(text));
        const int line = skipped ? source->extraSelections().first().cursor.blockNumber() : 0;

        // Inserting an earlier file also shifts the selected file's document index.
        writeSource(directory.filePath("a.py"), "def added():\n    pass\n");
        writeSource(path, "# edited\n\n" + text);
        QTRY_VERIFY_WITH_TIMEOUT(source->toPlainText().contains("# edited"), 10000);
        QVERIFY(!hasNode(graph, "previous#start"));
        QVERIFY(!hasNode(graph, "0#previous"));
        QCOMPARE(tree->currentIndex().data().toString(), selectedLabel);
        if (skipped) {
            QCOMPARE(source->extraSelections().size(), 1);
            QCOMPARE(source->extraSelections().first().cursor.blockNumber(), line + 2);
        }
    }
    void historyDropsDeletedCharts_data() {
        QTest::addColumn<bool>("currentDeleted");
        QTest::newRow("inactive") << false;
        QTest::newRow("current") << true;
    }
    void historyDropsDeletedCharts() {
        QFETCH(bool, currentDeleted);
        const auto uv = QStandardPaths::findExecutable("uv");
        if (uv.isEmpty())
            QSKIP("uv is needed for the real Python worker integration test");
        QTemporaryDir directory;
        QVERIFY(directory.isValid());
        const auto path = directory.filePath("history.py");
        writeSource(
            path, "def first():\n    pass\n\ndef removed():\n    pass\n\ndef last():\n    pass\n");
        const auto engine = defaultEngine();
        MainWindow window(engine.program, engine.arguments, engine.workingDirectory);
        window.openPaths({path});
        auto *graph = window.findChild<GraphView *>();
        auto *source = window.findChild<SourceView *>();
        auto *browser = window.findChild<ChartBrowser *>();
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "0#first"), 15000);
        for (const auto &name : {"first", "removed", "last"})
            browser->chartSelected(0, name);
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "last#start"), 10000);
        QAction *back = nullptr;
        QAction *forward = nullptr;
        for (auto *action : window.findChildren<QAction *>()) {
            if (action->text() == "Back")
                back = action;
            if (action->text() == "Forward")
                forward = action;
        }
        QVERIFY(back && forward);
        if (currentDeleted) {
            back->trigger();
            QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "removed#start"), 10000);
        }
        writeSource(path, "# edited\ndef first():\n    pass\n\ndef last():\n    pass\n");
        QTRY_VERIFY_WITH_TIMEOUT(source->toPlainText().contains("# edited"), 10000);
        if (currentDeleted) {
            QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "first#start"), 10000);
            QVERIFY(forward->isEnabled());
            forward->trigger();
        }
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "last#start"), 10000);
        back->trigger();
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "first#start"), 10000);
        back->trigger();
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "0#first"), 10000);
        QVERIFY(!back->isEnabled());
        forward->trigger();
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "first#start"), 10000);
        forward->trigger();
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "last#start"), 10000);
        QVERIFY(!forward->isEnabled());
    }
    void defaultWorkerIgnoresLaunchDirectory() {
        if (QStandardPaths::findExecutable("uv").isEmpty())
            QSKIP("uv is needed for the real Python worker integration test");
        QTemporaryDir directory;
        QVERIFY(directory.isValid());
        // A checkout that ships its own `pyflowcharts` package, as an untrusted one could.
        const auto marker = directory.filePath("imported");
        QVERIFY(QDir(directory.path()).mkpath("pyflowcharts/desktop"));
        writeSource(directory.filePath("pyflowcharts/__init__.py"),
                    "open(r'" + marker.toUtf8() + "', 'w').close()\n");
        writeSource(directory.filePath("pyflowcharts/desktop/__init__.py"), "");
        writeSource(directory.filePath("pyflowcharts/desktop/__main__.py"), "");
        writeSource(directory.filePath("source.py"), "def inside():\n    pass\n");
        CurrentDirectory restore;
        QVERIFY(QDir::setCurrent(directory.path()));
        const auto engine = defaultEngine();
        MainWindow window(engine.program, engine.arguments, engine.workingDirectory);
        // Source paths stay relative to the launch directory, not the worker's.
        window.openPaths({"source.py"});
        auto *graph = window.findChild<GraphView *>();
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "0#inside"), 15000);
        QVERIFY(!QFile::exists(marker));
    }
    void realWorkerRendersNavigatesAndReloads() {
        const auto uv = QStandardPaths::findExecutable("uv");
        if (uv.isEmpty())
            QSKIP("uv is needed for the real Python worker integration test");
        QTemporaryDir directory;
        QVERIFY(directory.isValid());
        const auto path = directory.filePath(QString::fromUtf8("café.py"));
        const QByteArray text =
            "def target():\n    return 7\n\n"
            "def caller(value):\n    if value:\n        return target()\n    return 0\n\n"
            "caller(True)\n";
        writeSource(path, text);
        const auto engine = defaultEngine();
        MainWindow window(engine.program, engine.arguments, engine.workingDirectory);
        window.show();
        window.openPaths({path});
        auto *graph = window.findChild<GraphView *>();
        auto *source = window.findChild<SourceView *>();
        auto *browser = window.findChild<ChartBrowser *>();
        QVERIFY(graph && source && browser);
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "0#caller"), 15000);
        browser->chartSelected(0, "caller");
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "caller#start"), 10000);
        QVERIFY(source->toPlainText().contains("return target()"));
        QString callNode;
        for (auto *item : graph->scene()->items()) {
            if (item->data(0).toString().startsWith("caller#L6"))
                callNode = item->data(0).toString();
        }
        QVERIFY(!callNode.isEmpty());
        graph->selectNode(callNode);
        QVERIFY(!source->extraSelections().isEmpty());
        graph->nodeActivated(callNode);
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "target#start"), 10000);
        browser->chartSelected(0, "caller");
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "caller#start"), 10000);
        graph->selectNode(callNode);
        graph->zoom(1.7);
        const auto transform = graph->transform();
        QSignalSpy selections(graph, &GraphView::nodeSelected);
        writeSource(path, text + "\n# edited\n");
        QTRY_VERIFY_WITH_TIMEOUT(source->toPlainText().contains("# edited"), 10000);
        QTRY_VERIFY_WITH_TIMEOUT(!selections.isEmpty(), 10000);
        QCOMPARE(graph->transform(), transform);
        QCOMPARE(graph->selectedNode(), callNode);

        // Reload must not clear its own input list when passed the stored paths.
        QAction *reload = nullptr;
        for (auto *action : window.findChildren<QAction *>()) {
            if (action->shortcut() == QKeySequence::Refresh)
                reload = action;
        }
        QVERIFY(reload);
        reload->trigger();
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "0#caller"), 10000);
        browser->chartSelected(0, "caller");
        QTRY_VERIFY_WITH_TIMEOUT(hasNode(graph, "caller#start"), 10000);
        if (const auto screenshot = qEnvironmentVariable("FLOWCHARTS_SCREENSHOT");
            !screenshot.isEmpty())
            QVERIFY(window.grab().save(screenshot));
    }
};
QTEST_MAIN(IntegrationTest)
#include "test_integration.moc"

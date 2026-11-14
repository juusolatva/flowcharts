#include "chartbrowser.h"
#include "graphview.h"
#include "mainwindow.h"
#include "sourceview.h"

#include <QAction>
#include <QFile>
#include <QGraphicsItem>
#include <QGraphicsScene>
#include <QSignalSpy>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QTreeView>
#include <QtTest>

using namespace flowcharts;

static bool hasNode(GraphView *view, const QString &prefix) {
    for (auto *item : view->scene()->items()) {
        if (item->data(0).toString().startsWith(prefix))
            return true;
    }
    return false;
}

static void writeSource(const QString &path, const QByteArray &text) {
    QFile file(path);
    QVERIFY(file.open(QIODevice::WriteOnly));
    QCOMPARE(file.write(text), text.size());
}

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
        MainWindow window(uv, {"run", "--project", FLOWCHARTS_PROJECT_DIR, "--no-sync", "python",
                               "-u", "-m", "pyflowcharts.desktop"});
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
        QCOMPARE(file.data(Qt::ToolTipRole).toString(), path);
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
        MainWindow window(uv, {"run", "--project", FLOWCHARTS_PROJECT_DIR, "--no-sync", "python",
                               "-u", "-m", "pyflowcharts.desktop"});
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

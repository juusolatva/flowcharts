#include "graphview.h"
#include "mainwindow.h"

#include <QAction>
#include <QDockWidget>
#include <QLabel>
#include <QPlainTextEdit>
#include <QStatusBar>
#include <QTemporaryDir>
#include <QtTest>

using namespace flowcharts;

namespace {
QString fakeEngine() {
    return QCoreApplication::applicationDirPath() + "/fake-engine";
}

QLabel *engineStatus(const MainWindow &window) {
    return window.findChild<QLabel *>("engineStatus");
}

// Samples the engine status for the given time and reports whether it ever read "Working…".
bool showedWorking(const MainWindow &window, int milliseconds) {
    QElapsedTimer timer;
    timer.start();
    while (timer.elapsed() < milliseconds) {
        if (engineStatus(window)->text() == QString("Working…"))
            return true;
        QTest::qWait(10);
    }
    return false;
}
} // namespace

class MainWindowTest : public QObject {
    Q_OBJECT
private slots:
    void backgroundRefreshDoesNotFlickerStatus() {
        MainWindow window(fakeEngine(), {"--refresh-delay=150"});
        window.show();
        window.openPaths({"/project"});
        QTRY_COMPARE(engineStatus(window)->text(), QString("Ready"));
        QVERIFY(!showedWorking(window, 2500));
    }
    void longWorkStillShowsWorking() {
        MainWindow window(fakeEngine(), {"--refresh-delay=1500"});
        window.show();
        window.openPaths({"/project"});
        QTRY_COMPARE(engineStatus(window)->text(), QString("Ready"));
        QVERIFY(showedWorking(window, 3000));
        QTRY_COMPARE_WITH_TIMEOUT(engineStatus(window)->text(), QString("Ready"), 3000);
    }
    void refreshFailureOfPreviousWorkspaceIsIgnored() {
        MainWindow window(fakeEngine(), {"--refresh-delay=1000", "--refresh-fails"});
        window.show();
        window.openPaths({"/old"});
        QTRY_COMPARE(engineStatus(window)->text(), QString("Ready"));
        // A refresh of the current workspace that fails is reported.
        QTRY_VERIFY_WITH_TIMEOUT(window.statusBar()->currentMessage().contains("refresh failed"),
                                 5000);
        window.statusBar()->clearMessage();
        // Reopen while the next refresh is still in flight; its failure is about /old.
        QVERIFY(showedWorking(window, 3000));
        window.openPaths({"/new"});
        QTRY_COMPARE_WITH_TIMEOUT(engineStatus(window)->text(), QString("Ready"), 3000);
        QVERIFY(!window.statusBar()->currentMessage().contains("refresh failed"));
    }
    void diagnosticsDockClosesWhenProblemsAreResolved() {
        MainWindow window(fakeEngine(), {"--diagnostics-once"});
        window.show();
        const auto *dock = window.findChild<QDockWidget *>("diagnosticsDock");
        const auto *text = dock->findChild<QPlainTextEdit *>();
        window.openPaths({"/project"});
        QTRY_VERIFY(dock->isVisible());
        QCOMPARE(text->toPlainText(), QString("problem"));
        window.openPaths({"/project"});
        QTRY_VERIFY(!dock->isVisible());
        QVERIFY(text->toPlainText().isEmpty());
    }
    void repeatedRefreshFailureIsReportedOnce() {
        MainWindow window(fakeEngine(), {"--refresh-fails"});
        window.show();
        auto *dock = window.findChild<QDockWidget *>("diagnosticsDock");
        const auto *text = dock->findChild<QPlainTextEdit *>();
        window.openPaths({"/project"});
        QTRY_VERIFY_WITH_TIMEOUT(text->toPlainText().contains("refresh failed"), 5000);
        dock->hide();
        QTest::qWait(2500);
        QCOMPARE(text->toPlainText().count("refresh failed"), 1);
        QVERIFY(!dock->isVisible());
    }
    void restartedEngineKeepsItsWorkingDirectory() {
        QTemporaryDir directory;
        QVERIFY(directory.isValid());
        MainWindow window(fakeEngine(), {"--report-cwd"}, directory.path());
        const auto *text =
            window.findChild<QDockWidget *>("diagnosticsDock")->findChild<QPlainTextEdit *>();
        window.openPaths({"/project"});
        QTRY_VERIFY(!text->toPlainText().isEmpty());
        const auto first = text->toPlainText().split('\n');
        QCOMPARE(first.size(), 2);
        QCOMPARE(QDir(first[0]).canonicalPath(), QDir(directory.path()).canonicalPath());
        int restarts = 0;
        for (auto *action : window.findChildren<QAction *>()) {
            if (action->text() == "Restart analysis &engine") {
                action->trigger();
                ++restarts;
            }
        }
        QCOMPARE(restarts, 1);
        // The restart clears the diagnostics until the new process reports its id.
        QTRY_VERIFY(text->toPlainText().split('\n').value(1, first[1]) != first[1]);
        QCOMPARE(text->toPlainText().split('\n')[0], first[0]);
    }
    void statusLabelsShowSourceTextLiterally() {
        // Node titles come from source code; a label like "<b>x</b>" must not become markup.
        MainWindow window(fakeEngine(), {});
        for (const auto *name : {"selection", "engineStatus"}) {
            const auto *label = window.findChild<QLabel *>(name);
            QVERIFY(label);
            QCOMPARE(label->textFormat(), Qt::PlainText);
        }
    }
    void failedOpenReplacesAnalysingPlaceholder() {
        MainWindow window(fakeEngine(), {"--open-fails"});
        window.show();
        const auto *graph = window.findChild<GraphView *>();
        window.openPaths({"/project"});
        QTRY_VERIFY(graph->message().contains("open failed"));
    }
};
QTEST_MAIN(MainWindowTest)
#include "test_mainwindow.moc"

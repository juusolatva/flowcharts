#include "mainwindow.h"

#include <QDockWidget>
#include <QLabel>
#include <QPlainTextEdit>
#include <QStatusBar>
#include <QtTest>

using namespace flowcharts;

namespace {
QString fakeEngine() {
    return QCoreApplication::applicationDirPath() + "/fake-engine";
}

QLabel *engineStatus(MainWindow &window) {
    return window.findChild<QLabel *>("engineStatus");
}

// Samples the engine status for the given time and reports whether it ever read "Working…".
bool showedWorking(MainWindow &window, int milliseconds) {
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
        auto *dock = window.findChild<QDockWidget *>("diagnosticsDock");
        auto *text = dock->findChild<QPlainTextEdit *>();
        window.openPaths({"/project"});
        QTRY_VERIFY(dock->isVisible());
        QCOMPARE(text->toPlainText(), QString("problem"));
        window.openPaths({"/project"});
        QTRY_VERIFY(!dock->isVisible());
        QVERIFY(text->toPlainText().isEmpty());
    }
};
QTEST_MAIN(MainWindowTest)
#include "test_mainwindow.moc"

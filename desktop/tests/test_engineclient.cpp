#include "engineclient.h"

#include <QCoreApplication>
#include <QSignalSpy>
#include <QtTest>

using namespace flowcharts;

class EngineClientTest : public QObject {
    Q_OBJECT
private slots:
    void asynchronousRoundTripAndRecoverableError() {
        EngineClient client;
        QSignalSpy success(&client, &EngineClient::succeeded);
        QSignalSpy failure(&client, &EngineClient::failed);
        QSignalSpy fatal(&client, &EngineClient::fatalError);
        client.start(QCoreApplication::applicationDirPath() + "/fake-engine", {});
        auto first = client.request("open", {});
        QTRY_COMPARE(success.size(), 1);
        QCOMPARE(success[0][0].toLongLong(), first);
        client.request("fail", {});
        QTRY_COMPARE(failure.size(), 1);
        client.request("graph", {});
        QTRY_COMPARE(success.size(), 2);
        QVERIFY(fatal.isEmpty());
        QVERIFY(client.idle());
    }
    void unreadableFrameFailsOnlyTheActiveRequest() {
        EngineClient client;
        QSignalSpy success(&client, &EngineClient::succeeded);
        QSignalSpy failure(&client, &EngineClient::failed);
        QSignalSpy fatal(&client, &EngineClient::fatalError);
        client.start(QCoreApplication::applicationDirPath() + "/fake-engine", {});
        const auto rejected = client.request("reject", {});
        QTRY_COMPARE(failure.size(), 1);
        QCOMPARE(failure[0][0].toLongLong(), rejected);
        QCOMPARE(failure[0][2].toString(), QString("example"));
        const auto next = client.request("graph", {});
        QTRY_COMPARE(success.size(), 1);
        QCOMPARE(success[0][0].toLongLong(), next);
        QVERIFY(fatal.isEmpty());
    }
    void watchdogCoversLayoutButNotAnalysis() {
        EngineClient client;
        client.setLayoutTimeout(300);
        QSignalSpy success(&client, &EngineClient::succeeded);
        QSignalSpy fatal(&client, &EngineClient::fatalError);
        client.start(QCoreApplication::applicationDirPath() + "/fake-engine",
                     {"--refresh-delay=800", "--graph-delay=800"});
        // Analysing a large workspace can take as long as it needs.
        client.request("refresh", {});
        QTRY_COMPARE_WITH_TIMEOUT(success.size(), 1, 3000);
        QVERIFY(fatal.isEmpty());
        // A layout has its own 30-second limit in the engine, so a silent one means a hang.
        client.request("graph", {});
        QTRY_COMPARE_WITH_TIMEOUT(fatal.size(), 1, 3000);
        QCOMPARE(success.size(), 1);
    }
    void protocolMismatchIsFatal() {
        EngineClient client;
        QSignalSpy fatal(&client, &EngineClient::fatalError);
        client.start(QCoreApplication::applicationDirPath() + "/fake-engine", {});
        client.request("bad-version", {});
        QTRY_COMPARE(fatal.size(), 1);
        QVERIFY(fatal[0][0].toString().contains("protocol", Qt::CaseInsensitive));
    }
    void missingExecutableIsActionable() {
        EngineClient client;
        QSignalSpy fatal(&client, &EngineClient::fatalError);
        client.start("/nonexistent/flowcharts-engine", {});
        QTRY_COMPARE(fatal.size(), 1);
        QVERIFY(!client.running());
    }
    void requestAfterDisconnectFailsInsteadOfHanging() {
        EngineClient client;
        QSignalSpy fatal(&client, &EngineClient::fatalError);
        QSignalSpy failure(&client, &EngineClient::failed);
        client.start("/nonexistent/flowcharts-engine", {});
        QTRY_COMPARE(fatal.size(), 1);
        const auto id = client.request("open", {});
        QTRY_COMPARE(failure.size(), 1);
        QCOMPARE(failure[0][0].toLongLong(), id);
        QVERIFY(failure[0][3].toString().contains("Restart"));
    }
    void queuedGraphRequestsAreCoalesced() {
        EngineClient client;
        QSignalSpy success(&client, &EngineClient::succeeded);
        client.start(QCoreApplication::applicationDirPath() + "/fake-engine", {});
        // Whether "open" is already in flight depends on how quickly the platform reports the
        // process as started; either way the graphs queue behind it and only the newest remains.
        auto opening = client.request("open", {});
        client.request("graph", {{"marker", 1}});
        client.request("graph", {{"marker", 2}});
        auto last = client.request("graph", {{"marker", 3}});
        QTRY_COMPARE(success.size(), 2);
        QCOMPARE(success[0][0].toLongLong(), opening);
        QCOMPARE(success[1][0].toLongLong(), last);
        QTest::qWait(100);
        QCOMPARE(success.size(), 2);
    }
};
QTEST_GUILESS_MAIN(EngineClientTest)
#include "test_engineclient.moc"

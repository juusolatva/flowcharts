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
        // Before the process starts, only the newest pending graph should remain.
        client.start(QCoreApplication::applicationDirPath() + "/fake-engine", {});
        client.request("graph", {{"marker", 1}});
        client.request("graph", {{"marker", 2}});
        auto last = client.request("graph", {{"marker", 3}});
        QTRY_COMPARE(success.size(), 1);
        QCOMPARE(success[0][0].toLongLong(), last);
    }
};
QTEST_GUILESS_MAIN(EngineClientTest)
#include "test_engineclient.moc"

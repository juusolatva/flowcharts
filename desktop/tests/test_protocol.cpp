#include "protocol.h"

#include <QJsonArray>
#include <QtTest>

using namespace flowcharts;

class ProtocolTest : public QObject {
    Q_OBJECT
private slots:
    void fragmentedUnicodeAndMultipleFrames() {
        FrameReader reader;
        QVector<QJsonObject> frames;
        QString error;
        auto bytes =
            encodeRequest(42, "open", {{"paths", QJsonArray{QString::fromUtf8("café.py")}}});
        QVERIFY(reader.feed(bytes.left(bytes.size() - 2), frames, error));
        QVERIFY(frames.isEmpty());
        QVERIFY(reader.feed(bytes.right(2) + bytes, frames, error));
        QCOMPARE(frames.size(), 2);
        QCOMPARE(frames[0]["id"].toInt(), 42);
        QCOMPARE(frames[0]["protocol_version"].toInt(), 1);
        QCOMPARE(frames[0]["params"].toObject()["paths"].toArray()[0].toString(),
                 QString::fromUtf8("café.py"));
    }
    void rejectsInvalidFrames() {
        for (const QByteArray bytes : {QByteArray("broken\n"), QByteArray("[]\n")}) {
            FrameReader reader;
            QVector<QJsonObject> frames;
            QString error;
            QVERIFY(!reader.feed(bytes, frames, error));
            QVERIFY(!error.isEmpty());
        }
    }
    void boundsIndividualFramesNotWholeBatch() {
        FrameReader reader(8);
        QVector<QJsonObject> frames;
        QString error;
        QVERIFY(reader.feed("{}\r\n{}\n{}\n", frames, error));
        QCOMPARE(frames.size(), 3);
        QVERIFY(!reader.feed("123456789", frames, error));
        QVERIFY(!error.isEmpty());
        reader.clear();
        QVERIFY(reader.feed("{}\n", frames, error));
    }
    void acceptsEscapedLoneSurrogatesFromUndecodableFileNames() {
        // Python's surrogateescape keeps undecodable POSIX file-name bytes as lone surrogates;
        // the worker escapes them because raw lone surrogates are not valid UTF-8.
        FrameReader reader;
        QVector<QJsonObject> frames;
        QString error;
        QVERIFY2(reader.feed(R"({"source":"bad-\udcff.py"})"
                             "\n",
                             frames, error),
                 qPrintable(error));
        QCOMPARE(frames.size(), 1);
        QVERIFY(frames[0]["source"].toString().startsWith("bad-"));
        QVERIFY(frames[0]["source"].toString().endsWith(".py"));
    }
};
QTEST_GUILESS_MAIN(ProtocolTest)
#include "test_protocol.moc"

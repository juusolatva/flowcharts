#include "commandline.h"

#include <QDir>
#include <QtTest>

using namespace flowcharts;

class CommandLineTest : public QObject {
    Q_OBJECT
private slots:
    void defaultWorkerAndMultipleInputs() {
        QCommandLineParser parser;
        configureCommandLine(parser);
        QVERIFY(parser.parse({"flowcharts-desktop", "one file.py", QString::fromUtf8("café.py")}));
        const auto options = launchOptions(parser, "/project root");
        QCOMPARE(options.program, QString("uv"));
        QCOMPARE(options.arguments,
                 QStringList({"run", "--project", QDir::toNativeSeparators("/project root"),
                              "--no-sync", "python", "-u", "-m", "pyflowcharts.desktop"}));
        QCOMPARE(options.paths, QStringList({"one file.py", QString::fromUtf8("café.py")}));
    }
    void replacementEngineAndRepeatedArguments() {
        QCommandLineParser parser;
        configureCommandLine(parser);
        QVERIFY(parser.parse({"app", "--engine", "custom engine", "--engine-argument=--mode",
                              "--engine-argument=one value", "source/"}));
        const auto options = launchOptions(parser, "/unused");
        QCOMPARE(options.program, QString("custom engine"));
        QCOMPARE(options.arguments, QStringList({"--mode", "one value"}));
        QCOMPARE(options.paths, QStringList({"source/"}));
    }
    void defaultWorkerCanReceiveExtraArguments() {
        QCommandLineParser parser;
        configureCommandLine(parser);
        QVERIFY(parser.parse({"app", "--engine-argument=extra"}));
        QCOMPARE(launchOptions(parser, "/project").arguments.last(), QString("extra"));
    }
    void malformedFlagsAreRejected() {
        QCommandLineParser parser;
        configureCommandLine(parser);
        QVERIFY(!parser.parse({"app", "--unknown"}));
        QVERIFY(!parser.errorText().isEmpty());
        QVERIFY(!parser.parse({"app", "--engine"}));
    }
};
QTEST_GUILESS_MAIN(CommandLineTest)
#include "test_commandline.moc"

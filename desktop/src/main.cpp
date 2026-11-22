#include "commandline.h"
#include "mainwindow.h"

#include <QApplication>

int main(int argc, char **argv) {
    QApplication app(argc, argv);
    QCoreApplication::setApplicationName("flowcharts-desktop");
    QCoreApplication::setApplicationVersion("0.1.0");
    QCoreApplication::setOrganizationName("Flowcharts");
    QCommandLineParser parser;
    flowcharts::configureCommandLine(parser);
    parser.process(app);
    const auto options = flowcharts::launchOptions(parser, FLOWCHARTS_PROJECT_DIR);
    flowcharts::MainWindow window(options.program, options.arguments, options.workingDirectory);
    window.show();
    if (!options.paths.isEmpty())
        window.openPaths(options.paths);
    return app.exec();
}

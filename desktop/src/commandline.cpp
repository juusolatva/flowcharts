#include "commandline.h"

#include <QDir>

namespace flowcharts {

void configureCommandLine(QCommandLineParser &parser) {
    parser.setApplicationDescription("Native flowchart explorer (Qt Widgets)");
    parser.addHelpOption();
    parser.addVersionOption();
    parser.addPositionalArgument("paths", "Source files or directories to open", "[paths…]");
    parser.addOption({"engine", "Engine executable speaking desktop protocol v1", "program"});
    parser.addOption({"engine-argument", "Engine argument (repeatable)", "argument"});
}

LaunchOptions launchOptions(const QCommandLineParser &parser, const QString &projectDirectory) {
    LaunchOptions options;
    options.paths = parser.positionalArguments();
    if (parser.isSet("engine")) {
        options.program = parser.value("engine");
    } else {
        // Development builds use this checkout. A release bundle will supply its own engine.
        options.program = "uv";
        options.arguments = {"run",
                             "--project",
                             QDir::toNativeSeparators(projectDirectory),
                             "--no-sync",
                             "python",
                             "-u",
                             "-m",
                             "pyflowcharts.desktop"};
    }
    options.arguments.append(parser.values("engine-argument"));
    return options;
}

} // namespace flowcharts

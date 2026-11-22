#include "commandline.h"

#include <QDir>
#include <QStandardPaths>

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
        // Nothing in the launch directory may take part: `uv` is looked up on PATH only and
        // left empty when missing (on Windows, a bare program name can also be found in the
        // current directory), the worker runs in the checkout, and -P keeps the current
        // directory out of Python's module search. Source paths are made absolute by the GUI.
        options.program = QStandardPaths::findExecutable("uv");
        options.arguments = {"run", "--project", QDir::toNativeSeparators(projectDirectory),
                             "--no-sync"};
        options.arguments << "python" << "-P" << "-u" << "-m" << "pyflowcharts.desktop";
        options.workingDirectory = projectDirectory;
    }
    options.arguments.append(parser.values("engine-argument"));
    return options;
}

} // namespace flowcharts

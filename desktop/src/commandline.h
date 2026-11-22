#pragma once

#include <QCommandLineParser>

namespace flowcharts {

struct LaunchOptions {
    QString program;
    QStringList arguments;
    QStringList paths;
    QString workingDirectory; // empty: the caller's directory
};

void configureCommandLine(QCommandLineParser &parser);
LaunchOptions launchOptions(const QCommandLineParser &parser, const QString &projectDirectory);

} // namespace flowcharts

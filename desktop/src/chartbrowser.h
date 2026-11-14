#pragma once

#include "workspace.h"

#include <QWidget>

class QLineEdit;
class QTreeView;
class QStandardItemModel;
class QSortFilterProxyModel;

namespace flowcharts {

class ChartBrowser : public QWidget {
    Q_OBJECT
public:
    explicit ChartBrowser(QWidget *parent = nullptr);
    void setWorkspace(const Workspace &workspace);
    void selectChart(const ChartRef &ref);
    void focusSearch();
signals:
    void chartSelected(int document, const QString &qualname);
    void fileSelected(int document, const QString &message, int line);

private:
    QLineEdit *m_search;
    QTreeView *m_tree;
    QStandardItemModel *m_model;
    QSortFilterProxyModel *m_filter;
};

} // namespace flowcharts

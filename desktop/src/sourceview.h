#pragma once

#include <QPlainTextEdit>

namespace flowcharts {

class SourceView : public QPlainTextEdit {
    Q_OBJECT
public:
    explicit SourceView(QWidget *parent = nullptr);
    void highlightLines(int first, int last);
    void paintGutter(QPaintEvent *event);
signals:
    void lineClicked(int line);

protected:
    void resizeEvent(QResizeEvent *event) override;
    void mouseReleaseEvent(QMouseEvent *event) override;

private:
    int gutterWidth() const;
    void updateGutter();
    QWidget *m_gutter;
};

} // namespace flowcharts

<?xml version="1.0" encoding="UTF-8"?>

<xsl:stylesheet version="1.0"
                xmlns:xsl="http://www.w3.org/1999/XSL/Transform"
                xmlns:atom="http://www.w3.org/2005/Atom"
                exclude-result-prefixes="atom">
  <xsl:output method="html" encoding="UTF-8" indent="yes"/>
  <xsl:template match="/">
    <html lang="en">
      <head>
        <title><xsl:value-of select="atom:feed/atom:title"/></title>
        <meta name="viewport" content="width=device-width, initial-scale=1"/>
        <meta name="color-scheme" content="light dark"/>
        <style>
          body {
              margin: auto;
              max-width: 50em;
          }
          hgroup>* {
              margin: 0;
          }
          img.book-cover {
              max-width: min(30%, 9em);
              float: left; 
              padding-right: 1em;
              padding-top: 1em;
              padding-bottom: 1em;
          }
          hr {
          clear: left;
          }
          ul {
          list-style-position: inside;
          }
          .author {
              font-style: italic;
          }
          p.book-description {
              overflow-y: auto;
              max-height: 5em;
          }
        </style>

        <!-- <link rel="stylesheet" href="style.css"> -->
      </head>
  
      <body>
        <header>
          <h1><xsl:value-of select="atom:feed/atom:title"/></h1>
          <p>Updated <xsl:value-of select="atom:feed/atom:updated"/></p>
        </header>
        <main>
          <xsl:for-each select="atom:feed/atom:entry">
            <xsl:sort select="atom:author/atom:name"/>
            <hr/>
            <article>
              <hgroup>
                <h2>
                  <xsl:value-of select="atom:title"/>
                </h2>
                <p class="author">
                  <xsl:value-of select="atom:author/atom:name"/>
                </p>
              </hgroup>

              <xsl:for-each select="atom:link[@rel='http://opds-spec.org/image']">
                <img class="book-cover">
                  <xsl:attribute name="src">
                    <xsl:value-of select="@href"/>
                  </xsl:attribute>
                </img>
              </xsl:for-each>

              <xsl:if test="atom:content != ''">
                <p class="book-description">
                  <xsl:value-of select="atom:content"/>
                </p>
              </xsl:if>


              <section class="downloads">
                <h3>Available downloads</h3>
                <ul>
                  <xsl:for-each select="atom:link[@rel='http://opds-spec.org/acquisition']">
                    <li>
                      <a>
                        <xsl:attribute name="href">
                          <xsl:value-of select="@href"/>
                        </xsl:attribute>
                        <xsl:value-of select="@title"/>
                      </a> – <xsl:value-of select="."/>
                    </li>
                  </xsl:for-each>
                </ul>
              </section>
            </article>
          </xsl:for-each>
        </main>
      </body>
    </html>
  </xsl:template>

</xsl:stylesheet> 

require 'excon'
require 'fileutils'
require 'nokogiri'
require 'reverse_markdown'
require 'sanitize'
require 'time'
require 'toml'

ARTICLES_PATH = "./content/articles"
BASE_URL = "https://web.archive.org/web/20140228064137/http://blimpyb.com/"
IMAGES_PATH = "./content/images/"
MAX_PAGE = 5

def download_file(source_url, target_file)
  if File.exist?(target_file)
    puts "File exists: #{target_file}; skipping"
    return true
  end

  begin
    status, body, _final_url = get_url(source_url, raise_error: false)
    if status != 200 && status != 404
      raise("bad status: #{status}")
    end
    if status == 404
      puts "URL not found: #{source_url} / #{target_file}"
      return false
    end
  rescue ArgumentError
    if $!.message =~ /^Invalid URI: /
      puts "Invalid URL: #{source_url} / #{target_file}"
      return false
    end

    raise
  end

  dir = File.dirname(target_file)
  if !File.directory?(dir)
    puts "creating: #{dir}"
    FileUtils.mkdir_p(dir)
  end

  puts "writing: #{target_file}"
  File.write("#{target_file}", body)

  true
end

def get_url(url, raise_error: true, redirect: false)
  puts "getting: #{url}#{redirect ? " (redirect) " : ""}"
  resp = Excon.get(url)

  if resp.status != 200
    if resp.status == 302
      return get_url(resp.headers["Location"], redirect: true)
    end

    raise("bad status: #{resp.status}") if raise_error
  end

  # puts "body sample: #{resp.body[0..500]}..."

  [resp.status, resp.body, url]
end

def replace_single_image(slug_with_date, thumbnail_url:, alt_text:, full_url:, caption_text:)
  path = "#{IMAGES_PATH}/#{slug_with_date}"

  thumbnail_filename = File.basename(thumbnail_url)
  thumbnail_exists = download_file(thumbnail_url, "#{path}/#{thumbnail_filename}")

  full_filename = File.basename(full_url)
  full_exists = download_file(full_url, "#{path}/#{full_filename}")

  if thumbnail_exists && full_exists
    <<~EOS.strip
      <p text-align="center">
          <figure>
              <a href="../images/#{slug_with_date}/#{full_filename}">
                  <img src="../images/#{slug_with_date}/#{thumbnail_filename}" alt="#{alt_text}">
              </a>
              <figcaption><strong>#{caption_text}</strong></figcaption>
          </figure>
      </p>
    EOS
  elsif thumbnail_exists
    <<~EOS.strip
      <p text-align="center">
          <figure>
              <img src="../images/#{slug_with_date}/#{thumbnail_filename}" alt="#{alt_text}">
              <figcaption><strong>#{caption_text}</strong></figcaption>
          </figure>
      </p>
    EOS
  else
    "_(missing image)_ (**caption:** #{caption_text}; **alt:** #{alt_text})"
  end
end

def replace_images(content, slug_with_date)
  images = []

  content.gsub!(%r{^\[!\[\]\((.*?) "(.*)"\)\]\((.*)\)$\n\n^(.*)$}) do |match|
    # puts "FULL: #{match}"
    thumbnail_url = $1
    alt_text = $2
    full_url = $3
    caption_text = $4

    if caption_text.include?("does this look so")
    # require "pry" ; binding.pry
    end

    text_to_put_back = ""
    if caption_text.start_with?("*") || caption_text.length > 85
      text_to_put_back = "\n\n#{caption_text}"
      caption_text = alt_text
    end

    replace_single_image(slug_with_date, thumbnail_url: thumbnail_url, alt_text: alt_text, full_url: full_url, caption_text: caption_text) + text_to_put_back
  end

  content.gsub!(%r{^\[!\[\]\((.*?) "(.*)"\)\]\((.*?)\)\s*$}) do |match|
    # puts "FULL: #{match}"
    thumbnail_url = $1
    alt_text = $2
    full_url = $3
    caption_text = alt_text

    "\n" + replace_single_image(slug_with_date, thumbnail_url: thumbnail_url, alt_text: alt_text, full_url: full_url, caption_text: caption_text) + "\n"
  end

  content
end

def sanitize_content(content)
  content.gsub!(%r{<p>\*\*\*</p>}, "\n---\n")

  content = ReverseMarkdown.convert(content)

  content.gsub!(/^Popularity:.*$/, '')
  content.gsub!(/^Tags:.*$/, '')

  content.gsub!(%r{_ \*\*([^\*]+)\*\* _}, '_**\1**_')

  # kill double spacing in sentences
  content.gsub!(/&nbsp; /, ' ')

  content = Sanitize.fragment(content, Sanitize::Config::RESTRICTED)

  # fix blockquotes mauled by Sanitiz
  content.gsub!(%r{^&gt; }, '> ')

  # fix lists inside of blockquotes
  content.gsub!(%r{> -}, '> * ')

  # fix truncated lists
  content.gsub!(%r{^-(\w)}, '* \1')

  # and change other list types
  content.gsub!(%r{^- }, '* ')

  # get rid of blockquotes with empty space after them
  content.gsub!(%r{>\s+$}, '>')

  # strong quoted images ... for some reason
  content.gsub!(%r{\*\*\[!\[\]\((.*)\)\]\((.*)\)(.*)\*\*}, "[![](\\1)](\\2)\n\n\\3")

  # if we see any image, give it some breathing room, line collapse below will remove
  content.gsub!(%r{\[!\[\]\((.*?)\)\]\((.*?)\)}, "\n\n[![](\\1)](\\2)\n\n")

  # strip whitespace from end of lines
  content.gsub!(%r{ +$}, '')

  # collapse multiple newlines
  content.gsub!(%r{(\s*\n\s*){2,}}, "\n\n")

  content.strip!

  content
end

def process_entry(entry_url, title)
  path_segments = entry_url.value.split("/")
  slug = path_segments[path_segments.count - 2]

  slug.gsub!(/%[a-z0-9]{2}/, '')

  puts "\n\n---\n#{title} (#{slug})\n---\n\n"

  status, entry_body, final_entry_url = get_url(entry_url, raise_error: false)
  if status == 404
    puts "ENTRY IS GONE: #{title} / #{entry_url}"
    return
  end
  if status != 200
    raise("bad status: #{resp.status}")
  end

  entry_html = Nokogiri::HTML(entry_body)

  published_at = nil
  entry_html.css('#content .post .clock').each do |clock_element|
    #  e.g. " On February - 2 - 2012"
    published_at = Time.strptime(clock_element.text, " On %B - %d - %Y")
  end

  raise "no published_at for #{slug}!" if published_at.nil?

  slug_with_date = "#{published_at.strftime("%Y-%m-%d")}-#{slug}"

  entry_content = entry_html.css('.entry').to_html
  entry_content = sanitize_content(entry_content)

if slug.include?("mission-accomplished-i")
# require "pry" ; binding.pry
end

  entry_content = replace_images(entry_content, slug_with_date)

  # one final collapse
  entry_content.gsub!(%r{(\s*\n\s*){2,}}, "\n\n")

  toml_data = TOML::Generator.new({
    "title" => title,
    "published_at" => published_at.to_datetime.rfc3339,
    "wayback_machine_url" => final_entry_url,
  }).body

  filename = "#{ARTICLES_PATH}/#{slug_with_date}.md"
  puts "writing: #{filename}"

  File.write(filename, <<~EOS)
    +++
    #{toml_data.strip}
    +++

    # #{title}

    #{entry_content}
  EOS
end

def main
  entry_num = 0

  # inclusive
  for i in 1..MAX_PAGE
    done = false
    puts "entering page: #{i}"

    url = if i == 1
      BASE_URL
    else
      BASE_URL + "page/#{i}/"
    end

    _status, body, _final_url = get_url(url)

    html = Nokogiri::HTML(body)
    html.css('.boxpost h2 a').each do |element|
      entry_num += 1

      # used to ratchet what we're looking at right now for speed
      # next if entry_num < 23
      (done = true) && break if entry_num > 30

      entry_url = element.attributes["href"]
      title = element.text

      process_entry(entry_url, title)
    end

    break if done
  end
end

main
